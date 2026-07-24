import { mkdtemp, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const prepareTaskArtifactUploads = vi.fn();
const finalizeTaskArtifactUploads = vi.fn();

vi.mock("../../../signed-commit-artefacts", () => ({
  createSandboxPosthogClient: () => ({
    prepareTaskArtifactUploads,
    finalizeTaskArtifactUploads,
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
        name: "report.csv",
        type: "output",
        size: 7,
        storage_path: "tasks/artifacts/report.csv",
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
        name: "report.csv",
        type: "output",
        size: 7,
        storage_path: "tasks/artifacts/report.csv",
        uploaded_at: "2026-01-01T00:00:00Z",
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
      { path: "report.csv", contentType: "text/csv" },
    );

    expect(result.isError).toBeUndefined();
    expect(prepareTaskArtifactUploads).toHaveBeenCalledWith("task-1", "run-1", [
      { name: "report.csv", type: "output", size: 7, content_type: "text/csv" },
    ]);
    expect(fetch).toHaveBeenCalledWith(
      "https://storage.example/upload",
      expect.objectContaining({ method: "POST", body: expect.any(FormData) }),
    );
    expect(finalizeTaskArtifactUploads).toHaveBeenCalledWith(
      "task-1",
      "run-1",
      [
        expect.objectContaining({
          id: "artifact-1",
          type: "output",
          storage_path: "tasks/artifacts/report.csv",
        }),
      ],
    );
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
