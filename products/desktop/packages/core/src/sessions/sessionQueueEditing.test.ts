import {
  type AgentSession,
  type QueuedMessage,
  sendableQueuePrefixLength,
} from "@posthog/shared";
import { afterEach, describe, expect, it } from "vitest";
import { sessionStore, sessionStoreSetters } from "./sessionStore";

const RUN = "run-queue";
const TASK = "task-queue";

function seedQueue(messages: QueuedMessage[]) {
  sessionStoreSetters.setSession({
    taskRunId: RUN,
    taskId: TASK,
    events: [],
    messageQueue: messages,
    pendingPermissions: new Map(),
    status: "connected",
  } as unknown as AgentSession);
}

function queue(): QueuedMessage[] {
  return sessionStore.getState().sessions[RUN].messageQueue;
}

function msg(id: string, content: string): QueuedMessage {
  return { id, content, queuedAt: 1 };
}

afterEach(() => sessionStoreSetters.removeSession(RUN));

describe("moveQueuedMessage", () => {
  it("moves a message to a later position, preserving the others' order", () => {
    seedQueue([msg("a", "A"), msg("b", "B"), msg("c", "C")]);

    sessionStoreSetters.moveQueuedMessage(TASK, 0, 2);

    expect(queue().map((m) => m.id)).toEqual(["b", "c", "a"]);
  });

  it("moves a message to an earlier position", () => {
    seedQueue([msg("a", "A"), msg("b", "B"), msg("c", "C")]);

    sessionStoreSetters.moveQueuedMessage(TASK, 2, 0);

    expect(queue().map((m) => m.id)).toEqual(["c", "a", "b"]);
  });

  it.each([
    ["same index", 1, 1],
    ["from out of range", 5, 0],
    ["to out of range", 0, 9],
    ["negative index", -1, 0],
  ])("is a no-op for %s", (_label, from, to) => {
    seedQueue([msg("a", "A"), msg("b", "B"), msg("c", "C")]);

    sessionStoreSetters.moveQueuedMessage(TASK, from, to);

    expect(queue().map((m) => m.id)).toEqual(["a", "b", "c"]);
  });
});

describe("updateQueuedMessage", () => {
  it("replaces content and rawPrompt in place, keeping id and position", () => {
    seedQueue([msg("a", "A"), msg("b", "B")]);

    sessionStoreSetters.updateQueuedMessage(TASK, "a", {
      content: "edited A",
      rawPrompt: "edited A raw",
    });

    expect(queue().map((m) => m.id)).toEqual(["a", "b"]);
    expect(queue()[0].content).toBe("edited A");
    expect(queue()[0].rawPrompt).toBe("edited A raw");
    expect(queue()[1].content).toBe("B");
  });

  it("clears a stale rawPrompt when the patch omits it (local edit)", () => {
    seedQueue([{ id: "a", content: "A", rawPrompt: "old raw", queuedAt: 1 }]);

    sessionStoreSetters.updateQueuedMessage(TASK, "a", { content: "edited" });

    expect(queue()[0].content).toBe("edited");
    expect(queue()[0].rawPrompt).toBeUndefined();
  });

  it("is a no-op when the target id is not in the queue", () => {
    seedQueue([msg("a", "A")]);

    sessionStoreSetters.updateQueuedMessage(TASK, "missing", {
      content: "edited",
    });

    expect(queue()[0].content).toBe("A");
  });
});

describe("sendableQueuePrefixLength", () => {
  const q = (ids: string[]): Pick<AgentSession, "messageQueue"> => ({
    messageQueue: ids.map((id) => msg(id, id)),
  });

  it("returns the full length when nothing is being edited", () => {
    expect(sendableQueuePrefixLength(q(["a", "b", "c"]))).toBe(3);
  });

  it("stops at the edited message, so only earlier messages count", () => {
    expect(
      sendableQueuePrefixLength({
        ...q(["a", "b", "c"]),
        editingQueuedId: "b",
      }),
    ).toBe(1);
  });

  it("returns 0 when the head message is being edited", () => {
    expect(
      sendableQueuePrefixLength({
        ...q(["a", "b", "c"]),
        editingQueuedId: "a",
      }),
    ).toBe(0);
  });

  it("returns the full length when the edited id already left the queue", () => {
    expect(
      sendableQueuePrefixLength({
        ...q(["a", "b", "c"]),
        editingQueuedId: "gone",
      }),
    ).toBe(3);
  });
});

describe("editing hold on the drain", () => {
  it("set/clear stores and releases the edit hold", () => {
    seedQueue([msg("a", "A"), msg("b", "B")]);

    sessionStoreSetters.setEditingQueuedMessage(TASK, "b");
    expect(sessionStore.getState().sessions[RUN].editingQueuedId).toBe("b");

    sessionStoreSetters.clearEditingQueuedMessage(TASK);
    expect(
      sessionStore.getState().sessions[RUN].editingQueuedId,
    ).toBeUndefined();
  });

  it("stopAtEdited drains only the messages before the edited one", () => {
    seedQueue([msg("a", "A"), msg("b", "B"), msg("c", "C")]);
    sessionStoreSetters.setEditingQueuedMessage(TASK, "b");

    const combined = sessionStoreSetters.dequeueMessagesAsText(TASK, {
      stopAtEdited: true,
    });

    expect(combined).toBe("A");
    // The edited message and everything after it stay queued.
    expect(queue().map((m) => m.id)).toEqual(["b", "c"]);
  });

  it("stopAtEdited sends nothing when the head message is being edited", () => {
    seedQueue([msg("a", "A"), msg("b", "B")]);
    sessionStoreSetters.setEditingQueuedMessage(TASK, "a");

    expect(
      sessionStoreSetters.dequeueMessagesAsText(TASK, { stopAtEdited: true }),
    ).toBeNull();
    expect(
      sessionStoreSetters.dequeueMessages(TASK, { stopAtEdited: true }),
    ).toEqual([]);
    expect(queue().map((m) => m.id)).toEqual(["a", "b"]);
  });

  it("dequeueMessages with stopAtEdited returns the sendable prefix as raw items", () => {
    seedQueue([msg("a", "A"), msg("b", "B"), msg("c", "C")]);
    sessionStoreSetters.setEditingQueuedMessage(TASK, "c");

    const drained = sessionStoreSetters.dequeueMessages(TASK, {
      stopAtEdited: true,
    });

    expect(drained.map((m) => m.id)).toEqual(["a", "b"]);
    expect(queue().map((m) => m.id)).toEqual(["c"]);
  });

  it("drains the whole queue when stopAtEdited is not set, even mid-edit", () => {
    seedQueue([msg("a", "A"), msg("b", "B"), msg("c", "C")]);
    sessionStoreSetters.setEditingQueuedMessage(TASK, "b");

    // Cancel / recall paths pull everything back regardless of the edit hold.
    const combined = sessionStoreSetters.dequeueMessagesAsText(TASK);

    expect(combined).toBe("A\n\nB\n\nC");
    expect(queue()).toEqual([]);
  });
});

describe("sequential drain (max: 1)", () => {
  it("dequeueMessagesAsText drains only the head message, leaving the rest", () => {
    seedQueue([msg("a", "A"), msg("b", "B"), msg("c", "C")]);

    const first = sessionStoreSetters.dequeueMessagesAsText(TASK, { max: 1 });
    expect(first).toBe("A");
    expect(queue().map((m) => m.id)).toEqual(["b", "c"]);

    // The turn-end drain fires again per turn; each call takes the next head.
    const second = sessionStoreSetters.dequeueMessagesAsText(TASK, { max: 1 });
    expect(second).toBe("B");
    expect(queue().map((m) => m.id)).toEqual(["c"]);
  });

  it("dequeueMessages drains only the head message as a raw item", () => {
    seedQueue([msg("a", "A"), msg("b", "B")]);

    const drained = sessionStoreSetters.dequeueMessages(TASK, { max: 1 });

    expect(drained.map((m) => m.id)).toEqual(["a"]);
    expect(queue().map((m) => m.id)).toEqual(["b"]);
  });

  it("takes min(max, edit boundary): head sends, edited message and rest stay", () => {
    seedQueue([msg("a", "A"), msg("b", "B"), msg("c", "C")]);
    sessionStoreSetters.setEditingQueuedMessage(TASK, "b");

    const first = sessionStoreSetters.dequeueMessagesAsText(TASK, {
      stopAtEdited: true,
      max: 1,
    });
    expect(first).toBe("A");
    expect(queue().map((m) => m.id)).toEqual(["b", "c"]);

    // Next drain sends nothing: the new head is the message being edited.
    expect(
      sessionStoreSetters.dequeueMessagesAsText(TASK, {
        stopAtEdited: true,
        max: 1,
      }),
    ).toBeNull();
    expect(queue().map((m) => m.id)).toEqual(["b", "c"]);
  });
});
