import { parseDiffFromFile } from "@pierre/diffs";
import { describe, expect, it, vi } from "vitest";
import {
  type CodeReviewWorkspaceClient,
  RevertHunkService,
} from "./revertHunkService";

const FILE_PATH = "src/app.ts";
const REPO_PATH = "/repo";

const HEAD = "line one\nline two\nline three\n";
const WORKING = "line one\nline two changed\nline three\nline four\n";

function makeClient(
  overrides: Partial<CodeReviewWorkspaceClient> = {},
): CodeReviewWorkspaceClient {
  return {
    getFileAtHead: vi.fn(async () => HEAD),
    readRepoFile: vi.fn(async () => WORKING),
    writeRepoFile: vi.fn(async () => {}),
    ...overrides,
  };
}

describe("RevertHunkService", () => {
  it("reads head and working content then writes reverted content back", async () => {
    const client = makeClient();
    const service = new RevertHunkService(client);

    await service.revertHunk({
      repoPath: REPO_PATH,
      filePath: FILE_PATH,
      hunkIndex: 0,
    });

    expect(client.getFileAtHead).toHaveBeenCalledWith(REPO_PATH, FILE_PATH);
    expect(client.readRepoFile).toHaveBeenCalledWith(REPO_PATH, FILE_PATH);

    const writeMock = client.writeRepoFile as ReturnType<typeof vi.fn>;
    expect(writeMock).toHaveBeenCalledTimes(1);
    const [repoPath, filePath, content] = writeMock.mock.calls[0];
    expect(repoPath).toBe(REPO_PATH);
    expect(filePath).toBe(FILE_PATH);
    expect(content).toBe(HEAD);
  });

  it("reads head and working tree in parallel", async () => {
    const order: string[] = [];
    const client = makeClient({
      getFileAtHead: vi.fn(async () => {
        order.push("head:start");
        await Promise.resolve();
        order.push("head:end");
        return HEAD;
      }),
      readRepoFile: vi.fn(async () => {
        order.push("working:start");
        await Promise.resolve();
        order.push("working:end");
        return WORKING;
      }),
    });
    const service = new RevertHunkService(client);

    await service.revertHunk({
      repoPath: REPO_PATH,
      filePath: FILE_PATH,
      hunkIndex: 0,
    });

    expect(order.indexOf("working:start")).toBeLessThan(
      order.indexOf("head:end"),
    );
  });

  it("treats a missing head (newly added file) as empty when reverting", async () => {
    const client = makeClient({
      getFileAtHead: vi.fn(async () => null),
      readRepoFile: vi.fn(async () => "added line\n"),
    });
    const service = new RevertHunkService(client);

    await service.revertHunk({
      repoPath: REPO_PATH,
      filePath: FILE_PATH,
      hunkIndex: 0,
    });

    expect(client.getFileAtHead).toHaveBeenCalledWith(REPO_PATH, FILE_PATH);
    const writeMock = client.writeRepoFile as ReturnType<typeof vi.fn>;
    expect(writeMock.mock.calls[0][2]).toBe("");
  });

  it("propagates a write failure to the caller", async () => {
    const client = makeClient({
      writeRepoFile: vi.fn(async () => {
        throw new Error("disk full");
      }),
    });
    const service = new RevertHunkService(client);

    await expect(
      service.revertHunk({
        repoPath: REPO_PATH,
        filePath: FILE_PATH,
        hunkIndex: 0,
      }),
    ).rejects.toThrow("disk full");
  });
});

const SAMPLE_DIFF = parseDiffFromFile(
  { name: FILE_PATH, contents: HEAD },
  { name: FILE_PATH, contents: WORKING },
);

describe("RevertHunkService.revertHunkOptimistic", () => {
  it("applies the optimistic diff before awaiting the backend revert", async () => {
    const order: string[] = [];
    const client = makeClient({
      writeRepoFile: vi.fn(async () => {
        order.push("write");
      }),
    });
    const service = new RevertHunkService(client);

    await service.revertHunkOptimistic(
      {
        repoPath: REPO_PATH,
        filePath: FILE_PATH,
        hunkIndex: 0,
        fileDiff: SAMPLE_DIFF,
      },
      {
        onOptimisticApply: () => order.push("apply"),
        onRollback: () => order.push("rollback"),
      },
    );

    expect(order).toEqual(["apply", "write"]);
  });

  it("returns true and never rolls back when the revert succeeds", async () => {
    const service = new RevertHunkService(makeClient());
    const onRollback = vi.fn();

    const result = await service.revertHunkOptimistic(
      {
        repoPath: REPO_PATH,
        filePath: FILE_PATH,
        hunkIndex: 0,
        fileDiff: SAMPLE_DIFF,
      },
      { onOptimisticApply: vi.fn(), onRollback },
    );

    expect(result).toBe(true);
    expect(onRollback).not.toHaveBeenCalled();
  });

  it("rolls back and returns false when the backend revert fails", async () => {
    const client = makeClient({
      writeRepoFile: vi.fn(async () => {
        throw new Error("disk full");
      }),
    });
    const service = new RevertHunkService(client);
    const onRollback = vi.fn();

    const result = await service.revertHunkOptimistic(
      {
        repoPath: REPO_PATH,
        filePath: FILE_PATH,
        hunkIndex: 0,
        fileDiff: SAMPLE_DIFF,
      },
      { onOptimisticApply: vi.fn(), onRollback },
    );

    expect(result).toBe(false);
    expect(onRollback).toHaveBeenCalledTimes(1);
  });
});
