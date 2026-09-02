import { mkdtemp, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const prepareTaskArtifactUploads = vi.fn();
const finalizeTaskArtifactUploads = vi.fn();
const uploadTaskArtifacts = vi.fn();
const STABLE_DOWNLOAD_URL =
  "https://app.example/api/projects/2/tasks/task-1/runs/run-1/artifacts/artifact-1/download/";

vi.mock("../../../signed-commit-artefacts", () => ({
  createSandboxPosthogClient: () => ({
    prepareTaskArtifactUploads,
    finalizeTaskArtifactUploads,
    uploadTaskArtifacts,
  }),
}));

import { uploadArtifactTool } from "./upload-artifact";

describe("uploadArtifactTool", () => {
  let cwd: string;

  beforeEach(async () => {
    vi.clearAllMocks();
    cwd = await mkdtemp(path.join(os.tmpdir(), "upload-artifact-"));
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, status: 204 }),
    );
    prepareTaskArtifactUploads.mockResolvedValue([
      {
        id: "artifact-1",
        name: "report [final].csv",
        type: "output",
        size: 7,
        storage_path: "tasks/artifacts/report-final.csv",
        expires_in: 300,
        presigned_post: {
          url: "https://storage.example/upload",
          fields: { key: "value" },
        },
      },
    ]);
    finalizeTaskArtifactUploads.mockResolvedValue([
      {
        id: "artifact-1",
        name: "report [final].csv",
        type: "output",
        size: 7,
        storage_path: "tasks/artifacts/report-final.csv",
        uploaded_at: "2026-01-01T00:00:00Z",
        url: STABLE_DOWNLOAD_URL,
      },
    ]);
    uploadTaskArtifacts.mockResolvedValue([
      {
        id: "artifact-1",
        name: "report.csv",
        type: "output",
        size: 7,
        storage_path: "tasks/artifacts/report.csv",
        uploaded_at: "2026-01-01T00:00:00Z",
        url: STABLE_DOWNLOAD_URL,
      },
    ]);
  });

  afterEach(async () => {
    vi.restoreAllMocks();
    await rm(cwd, { recursive: true, force: true });
  });

  it("uploads and finalizes a workspace file as an output artifact", async () => {
    await writeFile(path.join(cwd, "report.csv"), "a,b\n1,2");

    const result = await uploadArtifactTool.handler(
      { cwd, taskId: "task-1", taskRunId: "run-1" },
      {
        path: "report.csv",
        name: "report [final].csv",
        contentType: "text/csv",
      },
    );

    expect(result.isError).toBeUndefined();
    expect(prepareTaskArtifactUploads).toHaveBeenCalledWith("task-1", "run-1", [
      {
        name: "report [final].csv",
        type: "output",
        source: "agent_output",
        size: 7,
        content_type: "text/csv",
      },
    ]);
    expect(fetch).toHaveBeenCalledWith(
      "https://storage.example/upload",
      expect.objectContaining({
        method: "POST",
        body: expect.any(FormData),
        // A stalled storage POST must abort instead of waiting out undici's
        // internal defaults, so the ≤10MB inline fallback stays fast.
        signal: expect.any(AbortSignal),
      }),
    );
    expect(finalizeTaskArtifactUploads).toHaveBeenCalledWith(
      "task-1",
      "run-1",
      [
        expect.objectContaining({
          id: "artifact-1",
          type: "output",
          source: "agent_output",
          storage_path: "tasks/artifacts/report-final.csv",
        }),
      ],
    );
    expect(result.content[0]?.text).toContain(
      String.raw`[report \[final\].csv](<${STABLE_DOWNLOAD_URL}>)`,
    );
  });

  it("falls back to the inline upload when object storage is unreachable", async () => {
    await writeFile(path.join(cwd, "report.csv"), "a,b\n1,2");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("fetch failed")),
    );

    const result = await uploadArtifactTool.handler(
      { cwd, taskId: "task-1", taskRunId: "run-1" },
      { path: "report.csv", contentType: "text/csv" },
    );

    expect(result.isError).toBeUndefined();
    expect(uploadTaskArtifacts).toHaveBeenCalledWith("task-1", "run-1", [
      expect.objectContaining({
        name: "report.csv",
        content: Buffer.from("a,b\n1,2").toString("base64"),
        content_encoding: "base64",
      }),
    ]);
    expect(result.content[0]?.text).toContain(
      `[report.csv](<${STABLE_DOWNLOAD_URL}>)`,
    );
  });

  it("removes credentials from a legacy presigned artifact reference", async () => {
    await writeFile(path.join(cwd, "report.csv"), "a,b\n1,2");
    finalizeTaskArtifactUploads.mockResolvedValueOnce([
      {
        id: "artifact-1",
        name: "report.csv",
        type: "output",
        size: 7,
        storage_path: "tasks/artifacts/report-final.csv",
        uploaded_at: "2026-01-01T00:00:00Z",
        url: "https://storage.example/tasks/artifacts/report.csv?X-Amz-Signature=secret",
      },
    ]);

    const result = await uploadArtifactTool.handler(
      { cwd, taskId: "task-1", taskRunId: "run-1" },
      { path: "report.csv", contentType: "text/csv" },
    );

    expect(result.content[0]?.text).toContain(
      "[report.csv](<https://storage.example/tasks/artifacts/report.csv>)",
    );
    expect(result.content[0]?.text).not.toContain("X-Amz-Signature");
    expect(result.content[0]?.text).not.toContain("secret");
  });

  it("surfaces the failure instead of falling back above the inline size limit", async () => {
    await writeFile(path.join(cwd, "big.bin"), Buffer.alloc(11 * 1024 * 1024));
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("fetch failed")),
    );

    const result = await uploadArtifactTool.handler(
      { cwd, taskId: "task-1", taskRunId: "run-1" },
      { path: "big.bin" },
    );

    expect(result.isError).toBe(true);
    expect(result.content[0]?.text).toContain("fetch failed");
    expect(uploadTaskArtifacts).not.toHaveBeenCalled();
  });

  it("rejects files outside the session workspace", async () => {
    const outside = await mkdtemp(path.join(os.tmpdir(), "outside-artifact-"));
    const outsideFile = path.join(outside, "secret.txt");
    await writeFile(outsideFile, "secret");

    try {
      const result = await uploadArtifactTool.handler(
        { cwd, taskId: "task-1", taskRunId: "run-1" },
        { path: outsideFile },
      );

      expect(result.isError).toBe(true);
      expect(result.content[0]?.text).toContain("inside the session workspace");
      expect(prepareTaskArtifactUploads).not.toHaveBeenCalled();
    } finally {
      await rm(outside, { recursive: true, force: true });
    }
  });
});
