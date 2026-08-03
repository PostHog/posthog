import { readdir } from "node:fs/promises";
import path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  decodeHandoffArtifact,
  HandoffCheckpointTracker,
} from "./handoff-checkpoint";
import {
  cloneTestRepo,
  createTestRepo,
  type TestRepo,
} from "./sagas/test-fixtures";
import type { HandoffLocalGitState } from "./types";

interface BundleStore {
  artifacts: Record<string, Buffer>;
  storagePath: string;
  manifest: Array<{ storage_path: string }>;
}

interface HandoffRepos {
  cloudRepo: TestRepo;
  localRepo: TestRepo;
  branch: string;
  localGitState: HandoffLocalGitState;
}

interface MockApiOptions {
  /** Store inline uploads as base64 text, like the backend did before content_encoding was sent. */
  legacyBase64AtRest?: boolean;
  /** Expose the prepare/finalize direct-upload endpoints. */
  directUploads?: boolean;
  /** Make inline uploads fail, like an API rejecting the request. */
  failInlineUploads?: boolean;
  /** Make finalize omit the uploaded artifact from its response. */
  unconfirmedFinalize?: boolean;
}

function createMockApi(store: BundleStore, options?: MockApiOptions) {
  let nextId = 0;
  const api: Record<string, unknown> = {
    uploadTaskArtifacts: async (
      _taskId: string,
      _runId: string,
      artifacts: Array<{
        name: string;
        content: string;
        content_encoding?: string;
      }>,
    ) => {
      if (options?.failInlineUploads) {
        throw new Error("Failed request: [413] Payload Too Large");
      }
      const uploaded = artifacts.map((artifact) => {
        const storagePath = `${store.storagePath}-${nextId++}-${artifact.name}`;
        store.artifacts[storagePath] =
          !options?.legacyBase64AtRest && artifact.content_encoding === "base64"
            ? Buffer.from(artifact.content, "base64")
            : Buffer.from(artifact.content, "utf-8");
        return { storage_path: storagePath };
      });
      for (const entry of uploaded) {
        store.manifest.push(entry);
      }
      return store.manifest;
    },
    downloadArtifact: async (
      _taskId: string,
      _runId: string,
      artifactPath: string,
    ) => {
      const content = store.artifacts[artifactPath];
      if (!content) return null;
      return content.buffer.slice(
        content.byteOffset,
        content.byteOffset + content.byteLength,
      );
    },
  };

  if (options?.directUploads) {
    api.prepareTaskArtifactUploads = async (
      _taskId: string,
      _runId: string,
      artifacts: Array<{ name: string; type: string; size: number }>,
    ) =>
      artifacts.map((artifact) => {
        const storagePath = `${store.storagePath}-${nextId++}-${artifact.name}`;
        return {
          id: `prepared-${storagePath}`,
          name: artifact.name,
          type: artifact.type,
          size: artifact.size,
          storage_path: storagePath,
          expires_in: 300,
          presigned_post: {
            url: "https://object-storage.test/upload",
            fields: { key: storagePath },
          },
        };
      });
    api.finalizeTaskArtifactUploads = async (
      _taskId: string,
      _runId: string,
      artifacts: Array<{ name: string; type: string; storage_path: string }>,
    ) => {
      if (options?.unconfirmedFinalize) {
        return [];
      }
      const finalized = artifacts.map((artifact) => ({
        name: artifact.name,
        type: artifact.type,
        storage_path: artifact.storage_path,
      }));
      for (const entry of finalized) {
        store.manifest.push(entry);
      }
      return finalized;
    };
  }

  return api;
}

function stubPresignedUploadFetch(store: BundleStore): void {
  vi.stubGlobal("fetch", async (_url: string, init?: { body?: unknown }) => {
    const form = init?.body as FormData;
    const key = form.get("key") as string;
    const file = form.get("file") as Blob;
    store.artifacts[key] = Buffer.from(await file.arrayBuffer());
    return new Response(null, { status: 204 });
  });
}

function createBundleStore(): BundleStore {
  return {
    storagePath: "gs://bucket/handoff",
    artifacts: {},
    manifest: [
      {
        storage_path: "gs://bucket/handoff-0-existing-checkpoint.pack",
      },
    ],
  };
}

function createTracker(
  repositoryPath: string,
  apiClient: ReturnType<typeof createMockApi>,
) {
  return new HandoffCheckpointTracker({
    repositoryPath,
    taskId: "task-1",
    runId: "run-1",
    apiClient: apiClient as never,
  });
}

async function seedCloudRepo(repo: TestRepo): Promise<void> {
  await repo.writeFile("tracked.txt", "base\n");
  await repo.writeFile("unstaged.txt", "base unstaged\n");
  await repo.git(["add", "tracked.txt", "unstaged.txt"]);
  await repo.git(["commit", "-m", "Add tracked files"]);
}

async function prepareHandoffRepos(
  cleanups: Array<() => Promise<void>>,
): Promise<HandoffRepos> {
  const cloudRepo = await createTestRepo("handoff-cloud");
  cleanups.push(cloudRepo.cleanup);
  await seedCloudRepo(cloudRepo);

  const localRepo = await cloneTestRepo(cloudRepo.path, "handoff-local");
  cleanups.push(localRepo.cleanup);

  const branch = await cloudRepo.git(["rev-parse", "--abbrev-ref", "HEAD"]);
  const localHead = await localRepo.git(["rev-parse", "HEAD"]);
  const upstreamHead = await localRepo.git(["rev-parse", `origin/${branch}`]);

  return {
    cloudRepo,
    localRepo,
    branch,
    localGitState: {
      head: localHead,
      branch,
      upstreamHead,
      upstreamRemote: "origin",
      upstreamMergeRef: `refs/heads/${branch}`,
    },
  };
}

async function makeCloudChanges(repo: TestRepo): Promise<void> {
  await repo.writeFile("committed.txt", "cloud commit\n");
  await repo.git(["add", "committed.txt"]);
  await repo.git(["commit", "-m", "Cloud commit"]);

  await repo.writeFile("tracked.txt", "staged change\n");
  await repo.git(["add", "tracked.txt"]);
  await repo.writeFile("unstaged.txt", "unstaged change\n");
  await repo.writeFile("untracked.txt", "untracked\n");
}

describe("HandoffCheckpointTracker", () => {
  const cleanups: Array<() => Promise<void>> = [];

  afterEach(async () => {
    vi.unstubAllGlobals();
    await Promise.all(cleanups.splice(0).map((cleanup) => cleanup()));
  });

  it("restores head, worktree, and index state for handoff replay", async () => {
    const { cloudRepo, localRepo, branch, localGitState } =
      await prepareHandoffRepos(cleanups);
    await makeCloudChanges(cloudRepo);

    const store = createBundleStore();
    const apiClient = createMockApi(store);
    const captureTracker = createTracker(cloudRepo.path, apiClient);

    const checkpoint = await captureTracker.captureForHandoff(localGitState);

    expect(checkpoint).not.toBeNull();
    if (!checkpoint) return;
    expect(Object.keys(store.artifacts).length).toBeGreaterThan(0);
    const gitCommonDirRaw = await cloudRepo.git([
      "rev-parse",
      "--git-common-dir",
    ]);
    const gitCommonDir = path.isAbsolute(gitCommonDirRaw)
      ? gitCommonDirRaw
      : path.resolve(cloudRepo.path, gitCommonDirRaw);
    expect(
      (await readdir(gitCommonDir)).filter((entry) =>
        entry.startsWith("posthog-code-handoff-"),
      ),
    ).toEqual([]);

    const applyTracker = createTracker(localRepo.path, apiClient);
    await applyTracker.applyFromHandoff(checkpoint);

    expect(await localRepo.git(["rev-parse", "HEAD"])).toBe(checkpoint.head);
    expect(await localRepo.git(["rev-parse", "--abbrev-ref", "HEAD"])).toBe(
      branch,
    );
    expect(await localRepo.readFile("committed.txt")).toBe("cloud commit\n");
    expect(await localRepo.readFile("tracked.txt")).toBe("staged change\n");
    expect(await localRepo.readFile("unstaged.txt")).toBe("unstaged change\n");
    expect(await localRepo.readFile("untracked.txt")).toBe("untracked\n");

    const status = await localRepo.git(["status", "--porcelain"]);
    expect(status).toContain("M  tracked.txt");
    expect(status).toContain(" M unstaged.txt");
    expect(status).toContain("?? untracked.txt");
    expect(localRepo.exists(".posthog/tmp")).toBe(false);
  });

  it("round-trips a cloud capture without local git state via direct-to-storage uploads", async () => {
    const originRepo = await createTestRepo("handoff-origin");
    cleanups.push(originRepo.cleanup);
    await seedCloudRepo(originRepo);

    const sandboxRepo = await cloneTestRepo(originRepo.path, "handoff-sandbox");
    cleanups.push(sandboxRepo.cleanup);
    const resumeRepo = await cloneTestRepo(originRepo.path, "handoff-resume");
    cleanups.push(resumeRepo.cleanup);

    await makeCloudChanges(sandboxRepo);

    const store = createBundleStore();
    const apiClient = createMockApi(store, { directUploads: true });
    stubPresignedUploadFetch(store);

    const captureTracker = createTracker(sandboxRepo.path, apiClient);
    const checkpoint = await captureTracker.captureForHandoff();

    expect(checkpoint).not.toBeNull();
    if (!checkpoint) return;
    expect(checkpoint.artifactPath).toBeDefined();
    expect(checkpoint.indexArtifactPath).toBeDefined();

    // Direct uploads store raw bytes, not base64 text.
    const pack = store.artifacts[checkpoint.artifactPath as string];
    expect(pack.subarray(0, 4).toString("utf-8")).toBe("PACK");

    const applyTracker = createTracker(resumeRepo.path, apiClient);
    await applyTracker.applyFromHandoff(checkpoint);

    expect(await resumeRepo.git(["rev-parse", "HEAD"])).toBe(checkpoint.head);
    expect(await resumeRepo.readFile("committed.txt")).toBe("cloud commit\n");
    expect(await resumeRepo.readFile("tracked.txt")).toBe("staged change\n");
    expect(await resumeRepo.readFile("unstaged.txt")).toBe("unstaged change\n");
    expect(await resumeRepo.readFile("untracked.txt")).toBe("untracked\n");

    const status = await resumeRepo.git(["status", "--porcelain"]);
    expect(status).toContain("M  tracked.txt");
    expect(status).toContain(" M unstaged.txt");
    expect(status).toContain("?? untracked.txt");
  });

  it("applies checkpoints whose artifacts are stored as legacy base64 text", async () => {
    const { cloudRepo, localRepo, localGitState } =
      await prepareHandoffRepos(cleanups);
    await makeCloudChanges(cloudRepo);

    const store = createBundleStore();
    const apiClient = createMockApi(store, { legacyBase64AtRest: true });
    const captureTracker = createTracker(cloudRepo.path, apiClient);

    const checkpoint = await captureTracker.captureForHandoff(localGitState);
    expect(checkpoint).not.toBeNull();
    if (!checkpoint) return;

    // Sanity-check the fixture: artifacts at rest are base64 text, not raw bytes.
    const pack = store.artifacts[checkpoint.artifactPath as string];
    expect(pack.subarray(0, 4).toString("utf-8")).not.toBe("PACK");

    const applyTracker = createTracker(localRepo.path, apiClient);
    await applyTracker.applyFromHandoff(checkpoint);

    expect(await localRepo.git(["rev-parse", "HEAD"])).toBe(checkpoint.head);
    expect(await localRepo.readFile("committed.txt")).toBe("cloud commit\n");
    expect(await localRepo.readFile("tracked.txt")).toBe("staged change\n");
  });

  it("returns null instead of a checkpoint when artifact uploads fail", async () => {
    const { cloudRepo, localGitState } = await prepareHandoffRepos(cleanups);
    await makeCloudChanges(cloudRepo);

    const store = createBundleStore();
    const apiClient = createMockApi(store, { failInlineUploads: true });
    const captureTracker = createTracker(cloudRepo.path, apiClient);

    const checkpoint = await captureTracker.captureForHandoff(localGitState);

    expect(checkpoint).toBeNull();
  });

  it("falls back to inline upload when finalize does not confirm the artifact", async () => {
    const { cloudRepo, localRepo, localGitState } =
      await prepareHandoffRepos(cleanups);
    await makeCloudChanges(cloudRepo);

    const store = createBundleStore();
    const apiClient = createMockApi(store, {
      directUploads: true,
      unconfirmedFinalize: true,
    });
    stubPresignedUploadFetch(store);
    const captureTracker = createTracker(cloudRepo.path, apiClient);

    const checkpoint = await captureTracker.captureForHandoff(localGitState);

    expect(checkpoint).not.toBeNull();
    if (!checkpoint) return;
    // The unconfirmed direct upload must not be referenced; the checkpoint
    // points at the inline upload, which stores decoded bytes.
    const pack = store.artifacts[checkpoint.artifactPath as string];
    expect(pack.subarray(0, 4).toString("utf-8")).toBe("PACK");

    const applyTracker = createTracker(localRepo.path, apiClient);
    await applyTracker.applyFromHandoff(checkpoint);
    expect(await localRepo.readFile("committed.txt")).toBe("cloud commit\n");
  });

  it("decodes raw and legacy base64 artifact buffers", () => {
    const rawPack = Buffer.concat([
      Buffer.from("PACK"),
      Buffer.from([0, 0, 0, 2, 255, 1, 2, 3]),
    ]);
    expect(decodeHandoffArtifact(rawPack)).toEqual(rawPack);

    const rawIndex = Buffer.concat([
      Buffer.from("DIRC"),
      Buffer.from([0, 0, 0, 2, 255, 4, 5, 6]),
    ]);
    expect(decodeHandoffArtifact(rawIndex)).toEqual(rawIndex);

    const legacyBase64 = Buffer.from(rawPack.toString("base64"), "utf-8");
    expect(decodeHandoffArtifact(legacyBase64)).toEqual(rawPack);
  });
});
