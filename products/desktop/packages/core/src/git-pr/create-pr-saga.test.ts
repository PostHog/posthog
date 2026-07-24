import { describe, expect, it, vi } from "vitest";
import { type CreatePrDeps, CreatePrSaga } from "./create-pr-saga";

function makeDeps(over: Partial<CreatePrDeps> = {}): CreatePrDeps {
  return {
    getCurrentBranch: vi.fn().mockResolvedValue("main"),
    createBranch: vi.fn().mockResolvedValue(undefined),
    getChangedFilesHead: vi.fn().mockResolvedValue([{ path: "x.ts" }]),
    generateCommitMessage: vi.fn().mockResolvedValue({ message: "feat: x" }),
    getHeadSha: vi.fn().mockResolvedValue("abc123"),
    commit: vi.fn().mockResolvedValue({ success: true, message: "ok" }),
    resetSoft: vi.fn().mockResolvedValue(undefined),
    getSyncStatus: vi.fn().mockResolvedValue({ hasRemote: true }),
    push: vi.fn().mockResolvedValue({ success: true, message: "ok" }),
    publish: vi.fn().mockResolvedValue({ success: true, message: "ok" }),
    generatePrTitleAndBody: vi
      .fn()
      .mockResolvedValue({ title: "T", body: "B" }),
    createPr: vi.fn().mockResolvedValue({
      success: true,
      message: "ok",
      prUrl: "https://github.com/o/r/pull/1",
    }),
    onProgress: vi.fn(),
    ...over,
  };
}

describe("CreatePrSaga", () => {
  it("runs commit -> push -> create-pr and returns the PR url", async () => {
    const deps = makeDeps();
    const saga = new CreatePrSaga(deps);

    const result = await saga.run({ directoryPath: "/repo" });

    expect(deps.commit).toHaveBeenCalled();
    expect(deps.push).toHaveBeenCalled();
    expect(deps.publish).not.toHaveBeenCalled();
    expect(deps.createPr).toHaveBeenCalled();
    if (!result.success) throw new Error(`saga failed: ${result.error}`);
    expect(result.data.prUrl).toBe("https://github.com/o/r/pull/1");
  });

  it("publishes instead of pushing when there is no remote", async () => {
    const deps = makeDeps({
      getSyncStatus: vi.fn().mockResolvedValue({ hasRemote: false }),
    });
    const saga = new CreatePrSaga(deps);

    await saga.run({ directoryPath: "/repo" });

    expect(deps.publish).toHaveBeenCalled();
    expect(deps.push).not.toHaveBeenCalled();
  });

  it("skips committing when there are no changed files", async () => {
    const deps = makeDeps({
      getChangedFilesHead: vi.fn().mockResolvedValue([]),
    });
    const saga = new CreatePrSaga(deps);

    await saga.run({ directoryPath: "/repo" });

    expect(deps.commit).not.toHaveBeenCalled();
    expect(deps.createPr).toHaveBeenCalled();
  });
});
