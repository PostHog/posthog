import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  type GitHandoffBranchDivergence,
  type GitHandoffCheckpoint,
  GitHandoffTracker,
} from "@posthog/git/handoff";
import type {
  PostHogAPIClient,
  PreparedTaskArtifactUpload,
} from "./posthog-api";
import type { GitCheckpoint, HandoffLocalGitState } from "./types";
import { Logger } from "./utils/logger";

/** Server-side cap on a single task-run artifact; larger files are skipped, not failed. */
const MAX_ARTIFACT_UPLOAD_BYTES = 30 * 1024 * 1024;
/** Inline uploads travel base64-encoded inside a JSON API body, so they must stay well under API request size limits. */
const MAX_INLINE_UPLOAD_BYTES = 10 * 1024 * 1024;

const PACK_MAGIC = Buffer.from("PACK");
const INDEX_MAGIC = Buffer.from("DIRC");

/**
 * Handoff artifacts used to be stored as base64 text (inline uploads without
 * content_encoding); direct-to-storage uploads store raw bytes. Detect raw
 * git payloads by their magic bytes and fall back to the legacy base64
 * decode otherwise.
 */
export function decodeHandoffArtifact(buffer: Buffer): Buffer {
  const head = buffer.subarray(0, 4);
  if (head.equals(PACK_MAGIC) || head.equals(INDEX_MAGIC)) {
    return buffer;
  }
  const text = buffer.toString("utf-8");
  if (/^[A-Za-z0-9+/]+={0,2}$/.test(text)) {
    return Buffer.from(text, "base64");
  }
  return buffer;
}

export interface HandoffCheckpointTrackerConfig {
  repositoryPath: string;
  taskId: string;
  runId: string;
  apiClient?: PostHogAPIClient;
  logger?: Logger;
}

type ArtifactTransfer<T extends object = Record<string, never>> = T & {
  rawBytes: number;
  wireBytes: number;
};

type UploadedArtifact = ArtifactTransfer<{ storagePath?: string }>;
type DownloadedArtifact = ArtifactTransfer<{ filePath: string }>;

type ArtifactKey = "pack" | "index";
type ArtifactSlotMap<T extends object> = Partial<
  Record<ArtifactKey, ArtifactTransfer<T>>
>;

interface UploadArtifactSpec {
  key: ArtifactKey;
  filePath?: string;
  name: string;
  contentType: string;
}

interface DownloadArtifactSpec {
  key: ArtifactKey;
  storagePath?: string;
  filePath: string;
  label: string;
}

type Uploads = ArtifactSlotMap<{ storagePath?: string }>;
type Downloads = ArtifactSlotMap<{ filePath: string }>;

export class HandoffCheckpointTracker {
  private repositoryPath: string;
  private taskId: string;
  private runId: string;
  private apiClient?: PostHogAPIClient;
  private logger: Logger;

  constructor(config: HandoffCheckpointTrackerConfig) {
    this.repositoryPath = config.repositoryPath;
    this.taskId = config.taskId;
    this.runId = config.runId;
    this.apiClient = config.apiClient;
    this.logger =
      config.logger ||
      new Logger({ debug: false, prefix: "[HandoffCheckpointTracker]" });
  }

  async captureForHandoff(
    localGitState?: HandoffLocalGitState,
  ): Promise<GitCheckpoint | null> {
    if (!this.apiClient) {
      throw new Error(
        "Cannot capture handoff checkpoint: API client not configured",
      );
    }

    const gitTracker = this.createGitTracker();
    const capture = await gitTracker.captureForHandoff(localGitState);

    try {
      const uploads = await this.uploadArtifacts([
        {
          key: "pack",
          filePath: capture.headPack?.path,
          name: `handoff/${capture.checkpoint.checkpointId}.pack`,
          contentType: "application/x-git-packed-objects",
        },
        {
          key: "index",
          filePath: capture.indexFile.path,
          name: `handoff/${capture.checkpoint.checkpointId}.index`,
          contentType: "application/octet-stream",
        },
      ]);

      // A checkpoint that references artifacts which never made it to storage
      // would make resume apply an incomplete git state; drop it instead.
      const packUploadMissing =
        !!capture.headPack && !uploads.pack?.storagePath;
      const indexUploadMissing = !uploads.index?.storagePath;
      if (packUploadMissing || indexUploadMissing) {
        this.logger.debug(
          "Discarding handoff checkpoint: required artifact uploads did not complete",
          {
            checkpointId: capture.checkpoint.checkpointId,
            packUploadMissing,
            indexUploadMissing,
            packBytes: capture.headPack?.rawBytes ?? 0,
            indexBytes: capture.indexFile.rawBytes,
          },
        );
        return null;
      }

      this.logCaptureMetrics(capture.checkpoint, uploads);

      return {
        ...capture.checkpoint,
        artifactPath: uploads.pack?.storagePath,
        indexArtifactPath: uploads.index?.storagePath,
      };
    } finally {
      await rm(capture.artifactDirectory, {
        recursive: true,
        force: true,
      }).catch(() => {});
    }
  }

  async applyFromHandoff(
    checkpoint: GitCheckpoint,
    options?: {
      localGitState?: HandoffLocalGitState;
      onDivergedBranch?: (
        divergence: GitHandoffBranchDivergence,
      ) => Promise<boolean>;
    },
  ): Promise<{ packBytes: number; indexBytes: number; totalBytes: number }> {
    if (!this.apiClient) {
      throw new Error(
        "Cannot apply handoff checkpoint: API client not configured",
      );
    }

    const gitTracker = this.createGitTracker();
    const tmpDir = await mkdtemp(
      join(tmpdir(), `posthog-code-handoff-${checkpoint.checkpointId}-`),
    );

    const packPath = join(tmpDir, `${checkpoint.checkpointId}.pack`);
    const indexPath = join(tmpDir, `${checkpoint.checkpointId}.index`);

    try {
      const downloads = await this.downloadArtifacts([
        {
          key: "pack",
          storagePath: checkpoint.artifactPath,
          filePath: packPath,
          label: "handoff pack",
        },
        {
          key: "index",
          storagePath: checkpoint.indexArtifactPath,
          filePath: indexPath,
          label: "handoff index",
        },
      ]);

      const applyResult = await gitTracker.applyFromHandoff({
        checkpoint: this.toGitCheckpoint(checkpoint),
        headPackPath: downloads.pack?.filePath,
        indexPath: downloads.index?.filePath,
        localGitState: options?.localGitState,
        onDivergedBranch: options?.onDivergedBranch,
      });

      this.logApplyMetrics(checkpoint, downloads, applyResult.totalBytes);

      return {
        packBytes: downloads.pack?.rawBytes ?? 0,
        indexBytes: downloads.index?.rawBytes ?? 0,
        totalBytes: applyResult.totalBytes,
      };
    } finally {
      await this.removeIfPresent(packPath);
      await this.removeIfPresent(indexPath);
      await rm(tmpDir, { recursive: true, force: true }).catch(() => {});
    }
  }

  private toGitCheckpoint(checkpoint: GitCheckpoint): GitHandoffCheckpoint {
    return {
      checkpointId: checkpoint.checkpointId,
      commit: checkpoint.commit,
      checkpointRef: checkpoint.checkpointRef,
      headRef: checkpoint.headRef,
      head: checkpoint.head,
      branch: checkpoint.branch,
      indexTree: checkpoint.indexTree,
      worktreeTree: checkpoint.worktreeTree,
      timestamp: checkpoint.timestamp,
      upstreamRemote: checkpoint.upstreamRemote ?? null,
      upstreamMergeRef: checkpoint.upstreamMergeRef ?? null,
      remoteUrl: checkpoint.remoteUrl ?? null,
    };
  }

  private async uploadArtifactFile(
    filePath: string,
    name: string,
    contentType: string,
  ): Promise<UploadedArtifact> {
    if (!this.apiClient) {
      return { rawBytes: 0, wireBytes: 0 };
    }

    const content = await readFile(filePath);
    if (content.byteLength > MAX_ARTIFACT_UPLOAD_BYTES) {
      this.logger.debug(
        "Skipping handoff artifact upload: file exceeds the artifact size limit",
        {
          name,
          rawBytes: content.byteLength,
          maxBytes: MAX_ARTIFACT_UPLOAD_BYTES,
        },
      );
      return { rawBytes: content.byteLength, wireBytes: 0 };
    }

    try {
      const storagePath = await this.uploadArtifactDirect(
        content,
        name,
        contentType,
      );
      if (storagePath) {
        return {
          storagePath,
          rawBytes: content.byteLength,
          wireBytes: content.byteLength,
        };
      }
    } catch (error) {
      this.logger.warn(
        "Direct artifact upload failed; falling back to inline upload",
        { name, error: error instanceof Error ? error.message : String(error) },
      );
    }

    return this.uploadArtifactInline(content, name, contentType);
  }

  private async uploadArtifactDirect(
    content: Buffer,
    name: string,
    contentType: string,
  ): Promise<string | undefined> {
    if (!this.apiClient) {
      return undefined;
    }

    const [prepared] = await this.apiClient.prepareTaskArtifactUploads(
      this.taskId,
      this.runId,
      [
        {
          name,
          type: "artifact",
          size: content.byteLength,
          content_type: contentType,
        },
      ],
    );
    if (!prepared) {
      return undefined;
    }

    await this.postToPresignedUrl(prepared, content, contentType);

    const [finalized] = await this.apiClient.finalizeTaskArtifactUploads(
      this.taskId,
      this.runId,
      [
        {
          id: prepared.id,
          name: prepared.name,
          type: "artifact",
          storage_path: prepared.storage_path,
          content_type: contentType,
        },
      ],
    );
    // An unconfirmed finalize means the artifact was never attached to the
    // run manifest; referencing it would break the download on resume.
    if (!finalized?.storage_path) {
      throw new Error(
        `Artifact finalize did not confirm ${name} at ${prepared.storage_path}`,
      );
    }
    return finalized.storage_path;
  }

  private async postToPresignedUrl(
    prepared: PreparedTaskArtifactUpload,
    content: Buffer,
    contentType: string,
  ): Promise<void> {
    const form = new FormData();
    for (const [key, value] of Object.entries(prepared.presigned_post.fields)) {
      form.append(key, value);
    }
    form.append(
      "file",
      new Blob([new Uint8Array(content)], { type: contentType }),
      prepared.name,
    );

    const response = await fetch(prepared.presigned_post.url, {
      method: "POST",
      body: form,
    });
    if (!response.ok) {
      throw new Error(
        `Presigned artifact upload failed: [${response.status}] ${response.statusText}`,
      );
    }
  }

  private async uploadArtifactInline(
    content: Buffer,
    name: string,
    contentType: string,
  ): Promise<UploadedArtifact> {
    if (!this.apiClient) {
      return { rawBytes: content.byteLength, wireBytes: 0 };
    }

    if (content.byteLength > MAX_INLINE_UPLOAD_BYTES) {
      this.logger.warn(
        "Skipping inline handoff artifact upload: file exceeds the inline upload limit",
        {
          name,
          rawBytes: content.byteLength,
          maxBytes: MAX_INLINE_UPLOAD_BYTES,
        },
      );
      return { rawBytes: content.byteLength, wireBytes: 0 };
    }

    const base64Content = content.toString("base64");
    try {
      const artifacts = await this.apiClient.uploadTaskArtifacts(
        this.taskId,
        this.runId,
        [
          {
            name,
            type: "artifact",
            content: base64Content,
            content_encoding: "base64",
            content_type: contentType,
          },
        ],
      );
      return {
        storagePath: artifacts.at(-1)?.storage_path,
        rawBytes: content.byteLength,
        wireBytes: Buffer.byteLength(base64Content, "utf-8"),
      };
    } catch (error) {
      this.logger.warn("Inline handoff artifact upload failed", {
        name,
        rawBytes: content.byteLength,
        error: error instanceof Error ? error.message : String(error),
      });
      return { rawBytes: content.byteLength, wireBytes: 0 };
    }
  }

  private async uploadArtifacts(specs: UploadArtifactSpec[]): Promise<Uploads> {
    const results: Array<readonly [ArtifactKey, UploadedArtifact | undefined]> =
      [];
    for (const spec of specs) {
      if (!spec.filePath) {
        results.push([spec.key, undefined] as const);
        continue;
      }
      results.push([
        spec.key,
        await this.uploadArtifactFile(
          spec.filePath,
          spec.name,
          spec.contentType,
        ),
      ] as const);
    }

    return Object.fromEntries(results) as Uploads;
  }

  private async downloadArtifactToFile(
    artifactPath: string,
    filePath: string,
    label: string,
  ): Promise<DownloadedArtifact> {
    if (!this.apiClient) {
      throw new Error(`Cannot download ${label}: API client not configured`);
    }

    const arrayBuffer = await this.apiClient.downloadArtifact(
      this.taskId,
      this.runId,
      artifactPath,
    );
    if (!arrayBuffer) {
      throw new Error(`Failed to download ${label} from ${artifactPath}`);
    }
    const binaryContent = decodeHandoffArtifact(Buffer.from(arrayBuffer));
    await writeFile(filePath, binaryContent);
    return {
      filePath,
      rawBytes: binaryContent.byteLength,
      wireBytes: arrayBuffer.byteLength,
    };
  }

  private async downloadArtifacts(
    specs: DownloadArtifactSpec[],
  ): Promise<Downloads> {
    const downloads = await Promise.all(
      specs.map(async (spec) => {
        if (!spec.storagePath) {
          return [spec.key, undefined] as const;
        }
        return [
          spec.key,
          await this.downloadArtifactToFile(
            spec.storagePath,
            spec.filePath,
            spec.label,
          ),
        ] as const;
      }),
    );

    return Object.fromEntries(downloads) as Downloads;
  }

  private createGitTracker(): GitHandoffTracker {
    return new GitHandoffTracker({
      repositoryPath: this.repositoryPath,
      logger: this.logger,
    });
  }

  private logCaptureMetrics(
    checkpoint: GitHandoffCheckpoint,
    uploads: Uploads,
  ): void {
    this.logger.debug("Captured handoff checkpoint", {
      branch: checkpoint.branch,
      head: checkpoint.head?.slice(0, 7),
      totalBytes: this.sumRawBytes(uploads.pack, uploads.index),
    });
  }

  private logApplyMetrics(
    checkpoint: GitCheckpoint,
    _downloads: Downloads,
    totalBytes: number,
  ): void {
    this.logger.debug("Applied handoff checkpoint", {
      branch: checkpoint.branch,
      head: checkpoint.head?.slice(0, 7),
      totalBytes,
    });
  }

  private sumRawBytes(
    ...artifacts: Array<{ rawBytes: number } | undefined>
  ): number {
    return artifacts.reduce(
      (total, artifact) => total + (artifact?.rawBytes ?? 0),
      0,
    );
  }

  private async removeIfPresent(filePath: string | undefined): Promise<void> {
    if (!filePath) {
      return;
    }
    await rm(filePath, { force: true }).catch(() => {});
  }
}
