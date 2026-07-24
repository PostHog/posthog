import { beforeEach, describe, expect, it } from "vitest";
import {
  pendingTaskPromptStoreApi,
  usePendingTaskPromptStore,
} from "./pendingTaskPromptStore";

describe("pendingTaskPromptStore", () => {
  beforeEach(() => {
    usePendingTaskPromptStore.setState({ byKey: {} });
  });

  it("stores prompts keyed by an arbitrary id", () => {
    pendingTaskPromptStoreApi.set("uuid-1", {
      promptText: "Fix the login bug",
      setAt: 1000,
    });

    expect(pendingTaskPromptStoreApi.get("uuid-1")).toEqual({
      promptText: "Fix the login bug",
      setAt: 1000,
    });
  });

  it("moves a prompt from a transient key to the real task id", () => {
    pendingTaskPromptStoreApi.set("uuid-1", {
      promptText: "Do the thing",
      setAt: 1000,
    });
    pendingTaskPromptStoreApi.move("uuid-1", "task-123");

    expect(pendingTaskPromptStoreApi.get("uuid-1")).toBeUndefined();
    expect(pendingTaskPromptStoreApi.get("task-123")).toEqual({
      promptText: "Do the thing",
      setAt: 1000,
    });
  });

  it("ignores move when the source key has no prompt", () => {
    pendingTaskPromptStoreApi.move("missing", "task-999");
    expect(pendingTaskPromptStoreApi.get("task-999")).toBeUndefined();
  });

  it("clears prompts", () => {
    pendingTaskPromptStoreApi.set("task-42", {
      promptText: "Hi",
      setAt: 1000,
    });
    pendingTaskPromptStoreApi.clear("task-42");
    expect(pendingTaskPromptStoreApi.get("task-42")).toBeUndefined();
  });

  it("preserves attachments through move", () => {
    pendingTaskPromptStoreApi.set("uuid-1", {
      promptText: "Look at this",
      setAt: 1000,
      attachments: [
        {
          kind: "image",
          uri: "file://x.png",
          fileName: "x.png",
          mimeType: "image/png",
        },
      ],
    });
    pendingTaskPromptStoreApi.move("uuid-1", "task-7");

    expect(pendingTaskPromptStoreApi.get("task-7")?.attachments).toHaveLength(
      1,
    );
  });
});
