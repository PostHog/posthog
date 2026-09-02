import { beforeEach, describe, expect, it } from "vitest";
import { useReviewDraftsStore } from "./reviewDraftsStore";

const TASK_A = "task-a";
const TASK_B = "task-b";

function resetStore() {
  useReviewDraftsStore.setState({ drafts: {}, batchEnabled: {} });
}

function addSampleDraft(
  taskId: string,
  overrides: Partial<{
    filePath: string;
    startLine: number;
    endLine: number;
    text: string;
  }> = {},
) {
  return useReviewDraftsStore.getState().addDraft(taskId, {
    filePath: overrides.filePath ?? "src/foo.ts",
    startLine: overrides.startLine ?? 1,
    endLine: overrides.endLine ?? 2,
    side: "additions",
    text: overrides.text ?? "comment text",
  });
}

describe("reviewDraftsStore", () => {
  beforeEach(() => {
    resetStore();
  });

  it("addDraft assigns an id and returns it", () => {
    const id = addSampleDraft(TASK_A);
    expect(id).toBeTruthy();
    const drafts = useReviewDraftsStore.getState().getDrafts(TASK_A);
    expect(drafts).toHaveLength(1);
    expect(drafts[0].id).toBe(id);
    expect(drafts[0].taskId).toBe(TASK_A);
    expect(drafts[0].text).toBe("comment text");
  });

  it("addDraft accumulates per task without cross-talk", () => {
    addSampleDraft(TASK_A, { text: "a1" });
    addSampleDraft(TASK_A, { text: "a2" });
    addSampleDraft(TASK_B, { text: "b1" });

    expect(useReviewDraftsStore.getState().getDraftCount(TASK_A)).toBe(2);
    expect(useReviewDraftsStore.getState().getDraftCount(TASK_B)).toBe(1);
  });

  it("updateDraft replaces text without changing other fields or duplicating", () => {
    const id = addSampleDraft(TASK_A, { text: "original" });
    useReviewDraftsStore.getState().updateDraft(TASK_A, id, "edited");

    const drafts = useReviewDraftsStore.getState().getDrafts(TASK_A);
    expect(drafts).toHaveLength(1);
    expect(drafts[0].text).toBe("edited");
    expect(drafts[0].id).toBe(id);
  });

  it("removeDraft removes only the matching draft", () => {
    const id1 = addSampleDraft(TASK_A, { text: "one" });
    const id2 = addSampleDraft(TASK_A, { text: "two" });

    useReviewDraftsStore.getState().removeDraft(TASK_A, id1);

    const drafts = useReviewDraftsStore.getState().getDrafts(TASK_A);
    expect(drafts).toHaveLength(1);
    expect(drafts[0].id).toBe(id2);
  });

  it("clearDrafts wipes drafts and batchEnabled for the task only", () => {
    addSampleDraft(TASK_A);
    addSampleDraft(TASK_B);
    useReviewDraftsStore.getState().setBatchEnabled(TASK_A, true);
    useReviewDraftsStore.getState().setBatchEnabled(TASK_B, true);

    useReviewDraftsStore.getState().clearDrafts(TASK_A);

    expect(useReviewDraftsStore.getState().getDraftCount(TASK_A)).toBe(0);
    expect(useReviewDraftsStore.getState().getDraftCount(TASK_B)).toBe(1);
    expect(useReviewDraftsStore.getState().isBatchEnabled(TASK_A)).toBe(false);
    expect(useReviewDraftsStore.getState().isBatchEnabled(TASK_B)).toBe(true);
  });

  it("getDraftsForFile filters by file path", () => {
    addSampleDraft(TASK_A, { filePath: "src/foo.ts", text: "foo" });
    addSampleDraft(TASK_A, { filePath: "src/bar.ts", text: "bar" });
    addSampleDraft(TASK_A, { filePath: "src/foo.ts", text: "foo2" });

    const fooDrafts = useReviewDraftsStore
      .getState()
      .getDraftsForFile(TASK_A, "src/foo.ts");
    expect(fooDrafts).toHaveLength(2);
    expect(fooDrafts.map((d) => d.text)).toEqual(["foo", "foo2"]);
  });

  it("isBatchEnabled defaults to true when drafts exist and no explicit value", () => {
    expect(useReviewDraftsStore.getState().isBatchEnabled(TASK_A)).toBe(false);
    addSampleDraft(TASK_A);
    expect(useReviewDraftsStore.getState().isBatchEnabled(TASK_A)).toBe(true);
  });

  it("isBatchEnabled honors explicit setBatchEnabled even with drafts present", () => {
    addSampleDraft(TASK_A);
    useReviewDraftsStore.getState().setBatchEnabled(TASK_A, false);
    expect(useReviewDraftsStore.getState().isBatchEnabled(TASK_A)).toBe(false);
  });
});
