import type { ReadFileAsBase64 } from "@posthog/core/editor/cloud-prompt";
import { getFileName } from "@posthog/shared";
import { inject, injectable } from "inversify";
import {
  type BundleLocalSkill,
  CLOUD_ARTIFACT_BUNDLE_LOCAL_SKILL,
  CLOUD_ARTIFACT_READ_FILE_AS_BASE64,
  CLOUD_ARTIFACT_RESOLVE_SKILL_DEPENDENCIES,
  type CloudArtifactClient,
  type CloudArtifactUploadRequest,
  type CloudSkillBundleRef,
  type FinalizedCloudArtifact,
  type PreparedCloudArtifact,
  type ResolveSkillBundleDependencies,
} from "./cloudArtifactIdentifiers";

const ATTACHMENT_SOURCE = "posthog_code";
const SKILL_BUNDLE_SOURCE = "posthog_code_skill";
const DEFAULT_CONTENT_TYPE = "application/octet-stream";
const SKILL_BUNDLE_CONTENT_TYPE = "application/zip";
export const CLOUD_ATTACHMENT_MAX_SIZE_BYTES = 30 * 1024 * 1024;
export const CLOUD_PDF_ATTACHMENT_MAX_SIZE_BYTES = 10 * 1024 * 1024;

const CONTENT_TYPE_BY_EXTENSION: Record<string, string> = {
  bmp: "image/bmp",
  c: "text/plain",
  cc: "text/plain",
  conf: "text/plain",
  cpp: "text/plain",
  css: "text/css",
  csv: "text/csv",
  gif: "image/gif",
  go: "text/plain",
  h: "text/plain",
  html: "text/html",
  ini: "text/plain",
  java: "text/plain",
  jpeg: "image/jpeg",
  jpg: "image/jpeg",
  js: "text/javascript",
  json: "application/json",
  jsx: "text/javascript",
  log: "text/plain",
  md: "text/markdown",
  pdf: "application/pdf",
  png: "image/png",
  py: "text/x-python",
  rb: "text/plain",
  rs: "text/plain",
  sh: "text/x-shellscript",
  sql: "application/sql",
  svg: "image/svg+xml",
  toml: "application/toml",
  ts: "text/typescript",
  tsx: "text/typescript",
  txt: "text/plain",
  webp: "image/webp",
  xml: "application/xml",
  yaml: "application/yaml",
  yml: "application/yaml",
  zip: "application/zip",
};

interface LoadedCloudAttachment {
  filePath: string;
  bytes: Uint8Array<ArrayBuffer>;
  upload: CloudArtifactUploadRequest;
}

function base64ToUint8Array(base64: string): Uint8Array<ArrayBuffer> {
  const binary = atob(base64);
  const bytes = new Uint8Array(new ArrayBuffer(binary.length));

  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }

  return bytes;
}

function getFileExtension(filePath: string): string {
  const parts = getFileName(filePath).split(".");
  return parts.length > 1 ? (parts.at(-1)?.toLowerCase() ?? "") : "";
}

function inferContentType(filePath: string): string {
  return (
    CONTENT_TYPE_BY_EXTENSION[getFileExtension(filePath)] ??
    DEFAULT_CONTENT_TYPE
  );
}

function getCloudAttachmentMaxSizeBytes(
  filePath: string,
  contentType: string,
): number {
  const extension = getFileExtension(filePath);
  const normalizedContentType =
    contentType.split(";")[0]?.trim().toLowerCase() ?? "";

  if (extension === "pdf" || normalizedContentType === "application/pdf") {
    return CLOUD_PDF_ATTACHMENT_MAX_SIZE_BYTES;
  }

  return CLOUD_ATTACHMENT_MAX_SIZE_BYTES;
}

function getCloudAttachmentSizeError(
  filePath: string,
  maxSizeBytes: number,
): string {
  const maxMb = Math.floor(maxSizeBytes / (1024 * 1024));

  if (getFileExtension(filePath) === "pdf") {
    return `${getFileName(filePath)} exceeds the ${maxMb}MB attachment limit for PDFs in cloud runs`;
  }

  return `${getFileName(filePath)} exceeds the ${maxMb}MB attachment limit`;
}

@injectable()
export class CloudArtifactService {
  constructor(
    @inject(CLOUD_ARTIFACT_READ_FILE_AS_BASE64)
    private readonly readFileAsBase64: ReadFileAsBase64,
    @inject(CLOUD_ARTIFACT_BUNDLE_LOCAL_SKILL)
    private readonly bundleLocalSkill: BundleLocalSkill,
    @inject(CLOUD_ARTIFACT_RESOLVE_SKILL_DEPENDENCIES)
    private readonly resolveSkillBundleDependencies: ResolveSkillBundleDependencies,
  ) {}

  async uploadTaskStagedAttachments(
    client: CloudArtifactClient,
    taskId: string,
    filePaths: string[],
    skillBundles: CloudSkillBundleRef[] = [],
  ): Promise<string[]> {
    if (!filePaths.length && !skillBundles.length) {
      return [];
    }

    const attachments = [
      ...(await this.loadCloudAttachments(filePaths)),
      ...(await this.loadCloudSkillBundles(skillBundles)),
    ];
    const preparedArtifacts = await client.prepareTaskStagedArtifactUploads(
      taskId,
      attachments.map((attachment) => attachment.upload),
    );

    await this.uploadPreparedArtifacts(attachments, preparedArtifacts);

    const finalizedArtifacts = await client.finalizeTaskStagedArtifactUploads(
      taskId,
      preparedArtifacts,
    );

    return finalizedArtifacts.map((artifact) => artifact.id);
  }

  async uploadRunAttachments(
    client: CloudArtifactClient,
    taskId: string,
    runId: string,
    filePaths: string[],
    skillBundles: CloudSkillBundleRef[] = [],
  ): Promise<string[]> {
    if (!filePaths.length && !skillBundles.length) {
      return [];
    }

    const attachments = [
      ...(await this.loadCloudAttachments(filePaths)),
      ...(await this.loadCloudSkillBundles(skillBundles)),
    ];
    const preparedArtifacts = await client.prepareTaskRunArtifactUploads(
      taskId,
      runId,
      attachments.map((attachment) => attachment.upload),
    );

    await this.uploadPreparedArtifacts(attachments, preparedArtifacts);

    const finalizedArtifacts = await client.finalizeTaskRunArtifactUploads(
      taskId,
      runId,
      preparedArtifacts,
    );

    return finalizedArtifacts.map((artifact) => artifact.id);
  }

  private async loadCloudAttachments(
    filePaths: string[],
  ): Promise<LoadedCloudAttachment[]> {
    return Promise.all(
      filePaths.map(async (filePath) => {
        const base64 = await this.readFileAsBase64(filePath);
        if (!base64) {
          throw new Error(
            `Unable to read attached file ${getFileName(filePath)}`,
          );
        }

        const bytes = base64ToUint8Array(base64);
        const contentType = inferContentType(filePath);
        const maxSizeBytes = getCloudAttachmentMaxSizeBytes(
          filePath,
          contentType,
        );
        if (bytes.byteLength > maxSizeBytes) {
          throw new Error(getCloudAttachmentSizeError(filePath, maxSizeBytes));
        }
        return {
          filePath,
          bytes,
          upload: {
            name: getFileName(filePath),
            type: "user_attachment",
            source: ATTACHMENT_SOURCE,
            size: bytes.byteLength,
            content_type: contentType,
          },
        };
      }),
    );
  }

  private async loadCloudSkillBundles(
    skillBundleRefs: CloudSkillBundleRef[],
  ): Promise<LoadedCloudAttachment[]> {
    if (skillBundleRefs.length === 0) {
      return [];
    }
    // Pull in dependency skills the tagged ones declare, so a skill that needs
    // another arrives in the sandbox together with it.
    const expandedRefs =
      await this.resolveSkillBundleDependencies(skillBundleRefs);
    return Promise.all(
      expandedRefs.map(async (skillBundleRef) => {
        const bundle = await this.bundleLocalSkill(skillBundleRef);
        const bytes = base64ToUint8Array(bundle.contentBase64);
        if (bytes.byteLength !== bundle.size) {
          throw new Error(
            `Unable to prepare local skill ${skillBundleRef.name}`,
          );
        }
        if (bytes.byteLength > CLOUD_ATTACHMENT_MAX_SIZE_BYTES) {
          throw new Error(
            `${bundle.fileName} exceeds the 30MB attachment limit`,
          );
        }

        return {
          filePath: skillBundleRef.path,
          bytes,
          upload: {
            name: bundle.fileName,
            type: "skill_bundle",
            source: SKILL_BUNDLE_SOURCE,
            size: bytes.byteLength,
            content_type: SKILL_BUNDLE_CONTENT_TYPE,
            metadata: {
              skill_name: bundle.name,
              skill_source: bundle.source,
              content_sha256: bundle.contentSha256,
              bundle_format: "zip",
              schema_version: 1,
            },
          },
        };
      }),
    );
  }

  private async uploadPreparedArtifacts(
    attachments: LoadedCloudAttachment[],
    preparedArtifacts: PreparedCloudArtifact[],
  ): Promise<void> {
    if (attachments.length !== preparedArtifacts.length) {
      throw new Error("Prepared uploads do not match the selected attachments");
    }

    await Promise.all(
      preparedArtifacts.map(async (preparedArtifact, index) => {
        const attachment = attachments[index];
        const formData = new FormData();

        for (const [key, value] of Object.entries(
          preparedArtifact.presigned_post.fields,
        )) {
          formData.append(key, value);
        }

        formData.append(
          "file",
          new Blob([attachment.bytes], {
            type: attachment.upload.content_type || DEFAULT_CONTENT_TYPE,
          }),
          attachment.upload.name,
        );

        const response = await fetch(preparedArtifact.presigned_post.url, {
          method: "POST",
          body: formData,
        });

        if (!response.ok) {
          throw new Error(`Failed to upload ${attachment.upload.name}`);
        }
      }),
    );
  }
}

export type { FinalizedCloudArtifact };
