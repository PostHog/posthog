import { describe, expect, it } from "vitest";
import { useDraftStore } from "./draftStore";

describe("draftStore pending inserts", () => {
  it("keeps every send that arrives before the composer takes them", () => {
    const { actions } = useDraftStore.getState();
    actions.insertPendingContent("task-1", {
      segments: [{ type: "text", text: "first" }],
    });
    actions.insertPendingContent("task-1", {
      segments: [{ type: "text", text: "second" }],
    });

    expect(actions.takePendingInsert("task-1")).toEqual({
      segments: [
        { type: "text", text: "first" },
        { type: "text", text: "second" },
      ],
    });
    expect(actions.takePendingInsert("task-1")).toBeNull();
  });
});
