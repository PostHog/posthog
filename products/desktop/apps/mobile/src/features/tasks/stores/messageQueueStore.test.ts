import { beforeEach, describe, expect, it } from "vitest";
import type { PendingAttachment } from "../composer/attachments/types";
import {
  combineQueuedMessages,
  type QueuedMessage,
  useMessageQueueStore,
} from "./messageQueueStore";

function image(id: string): PendingAttachment {
  return {
    kind: "image",
    id,
    uri: `file://${id}.png`,
    fileName: `${id}.png`,
    mimeType: "image/png",
  };
}

describe("messageQueueStore", () => {
  beforeEach(() => {
    useMessageQueueStore.setState(
      { queuesByTaskId: {}, editingByTaskId: {} },
      false,
    );
  });

  it("enqueues messages in FIFO order", () => {
    const { enqueue, getQueue } = useMessageQueueStore.getState();
    enqueue("t1", "first", []);
    enqueue("t1", "second", []);
    enqueue("t1", "third", []);
    expect(getQueue("t1").map((m) => m.content)).toEqual([
      "first",
      "second",
      "third",
    ]);
  });

  it("keeps separate queues per task", () => {
    const { enqueue, getQueue } = useMessageQueueStore.getState();
    enqueue("t1", "a", []);
    enqueue("t2", "b", []);
    expect(getQueue("t1").map((m) => m.content)).toEqual(["a"]);
    expect(getQueue("t2").map((m) => m.content)).toEqual(["b"]);
  });

  it("drains the queue in order and clears it", () => {
    const { enqueue, drain, getQueue } = useMessageQueueStore.getState();
    enqueue("t1", "a", []);
    enqueue("t1", "b", []);
    expect(drain("t1").map((m) => m.content)).toEqual(["a", "b"]);
    expect(getQueue("t1")).toEqual([]);
    // A second drain on the emptied queue is a no-op.
    expect(drain("t1")).toEqual([]);
  });

  it("prepends restored messages at the head (failed-flush rollback)", () => {
    const { enqueue, drain, prepend, getQueue } =
      useMessageQueueStore.getState();
    enqueue("t1", "a", []);
    enqueue("t1", "b", []);
    const drained = drain("t1");

    // A new message arrives while the flush is in flight.
    enqueue("t1", "c", []);
    // Flush failed — the drained messages go back ahead of the newcomer.
    prepend("t1", drained);

    expect(getQueue("t1").map((m) => m.content)).toEqual(["a", "b", "c"]);
  });

  it.each([
    {
      name: "removes exactly the targeted message",
      contents: ["a", "b", "c"],
      removeIndex: 1,
      expected: ["a", "c"],
    },
    {
      name: "clears the entry once the last message is removed",
      contents: ["only"],
      removeIndex: 0,
      expected: [],
    },
  ])("$name", ({ contents, removeIndex, expected }) => {
    const { enqueue, remove, getQueue } = useMessageQueueStore.getState();
    for (const content of contents) enqueue("t1", content, []);
    remove("t1", getQueue("t1")[removeIndex].id);
    expect(getQueue("t1").map((m) => m.content)).toEqual(expected);
  });

  it("ignores removal of an unknown id", () => {
    const { enqueue, remove, getQueue } = useMessageQueueStore.getState();
    enqueue("t1", "a", []);
    remove("t1", "nope");
    expect(getQueue("t1").map((m) => m.content)).toEqual(["a"]);
  });
});

describe("move", () => {
  beforeEach(() => {
    useMessageQueueStore.setState(
      { queuesByTaskId: {}, editingByTaskId: {} },
      false,
    );
  });

  function seed(contents: string[]) {
    const { enqueue, getQueue } = useMessageQueueStore.getState();
    for (const content of contents) enqueue("t1", content, []);
    return getQueue("t1");
  }

  it("moves a message down one slot", () => {
    const [a] = seed(["a", "b", "c"]);
    useMessageQueueStore.getState().move("t1", a.id, "down");
    expect(
      useMessageQueueStore
        .getState()
        .getQueue("t1")
        .map((m) => m.content),
    ).toEqual(["b", "a", "c"]);
  });

  it("moves a message up one slot", () => {
    const queue = seed(["a", "b", "c"]);
    useMessageQueueStore.getState().move("t1", queue[2].id, "up");
    expect(
      useMessageQueueStore
        .getState()
        .getQueue("t1")
        .map((m) => m.content),
    ).toEqual(["a", "c", "b"]);
  });

  it.each([
    { name: "up at the head", index: 0, direction: "up" as const },
    { name: "down at the tail", index: 2, direction: "down" as const },
  ])("is a no-op moving $name", ({ index, direction }) => {
    const queue = seed(["a", "b", "c"]);
    useMessageQueueStore.getState().move("t1", queue[index].id, direction);
    expect(
      useMessageQueueStore
        .getState()
        .getQueue("t1")
        .map((m) => m.content),
    ).toEqual(["a", "b", "c"]);
  });

  it("ignores an unknown id", () => {
    seed(["a", "b"]);
    useMessageQueueStore.getState().move("t1", "nope", "up");
    expect(
      useMessageQueueStore
        .getState()
        .getQueue("t1")
        .map((m) => m.content),
    ).toEqual(["a", "b"]);
  });
});

describe("edit in place", () => {
  beforeEach(() => {
    useMessageQueueStore.setState(
      { queuesByTaskId: {}, editingByTaskId: {} },
      false,
    );
  });

  it("updates content and attachments in place, keeping id and position", () => {
    const { enqueue, update, getQueue } = useMessageQueueStore.getState();
    enqueue("t1", "a", []);
    enqueue("t1", "b", []);
    const target = getQueue("t1")[0];

    update("t1", target.id, { content: "edited", attachments: [image("x")] });

    const queue = useMessageQueueStore.getState().getQueue("t1");
    expect(queue.map((m) => m.id)).toEqual([target.id, getQueue("t1")[1].id]);
    expect(queue[0].content).toBe("edited");
    expect(queue[0].attachments.map((att) => att.id)).toEqual(["x"]);
    expect(queue[1].content).toBe("b");
  });

  it("is a no-op when the target id is gone", () => {
    const { enqueue, update, getQueue } = useMessageQueueStore.getState();
    enqueue("t1", "a", []);
    update("t1", "missing", { content: "edited", attachments: [] });
    expect(getQueue("t1")[0].content).toBe("a");
  });

  it("set/clear stores and releases the edit hold", () => {
    const { enqueue, getQueue, setEditing, clearEditing } =
      useMessageQueueStore.getState();
    enqueue("t1", "a", []);
    const id = getQueue("t1")[0].id;

    setEditing("t1", id);
    expect(useMessageQueueStore.getState().editingByTaskId.t1).toBe(id);

    clearEditing("t1");
    expect(useMessageQueueStore.getState().editingByTaskId.t1).toBeUndefined();
  });

  it("clears the edit hold when the edited message is removed", () => {
    const { enqueue, getQueue, setEditing, remove } =
      useMessageQueueStore.getState();
    enqueue("t1", "a", []);
    enqueue("t1", "b", []);
    const id = getQueue("t1")[0].id;
    setEditing("t1", id);

    remove("t1", id);

    expect(useMessageQueueStore.getState().editingByTaskId.t1).toBeUndefined();
    expect(
      useMessageQueueStore
        .getState()
        .getQueue("t1")
        .map((m) => m.content),
    ).toEqual(["b"]);
  });

  it("keeps the edit hold when a different message is removed", () => {
    const { enqueue, getQueue, setEditing, remove } =
      useMessageQueueStore.getState();
    enqueue("t1", "a", []);
    enqueue("t1", "b", []);
    const editingId = getQueue("t1")[1].id;
    setEditing("t1", editingId);

    remove("t1", getQueue("t1")[0].id);

    expect(useMessageQueueStore.getState().editingByTaskId.t1).toBe(editingId);
  });
});

describe("drain boundary (stopAtEdited)", () => {
  beforeEach(() => {
    useMessageQueueStore.setState(
      { queuesByTaskId: {}, editingByTaskId: {} },
      false,
    );
  });

  function seed(contents: string[]) {
    const { enqueue, getQueue } = useMessageQueueStore.getState();
    for (const content of contents) enqueue("t1", content, []);
    return getQueue("t1");
  }

  it("drains only the messages before the edited one", () => {
    const queue = seed(["a", "b", "c"]);
    useMessageQueueStore.getState().setEditing("t1", queue[1].id);

    const drained = useMessageQueueStore
      .getState()
      .drain("t1", { stopAtEdited: true });

    expect(drained.map((m) => m.content)).toEqual(["a"]);
    // The edited message and everything after it stay queued.
    expect(
      useMessageQueueStore
        .getState()
        .getQueue("t1")
        .map((m) => m.content),
    ).toEqual(["b", "c"]);
  });

  it("drains nothing when the head message is being edited", () => {
    const queue = seed(["a", "b"]);
    useMessageQueueStore.getState().setEditing("t1", queue[0].id);

    const drained = useMessageQueueStore
      .getState()
      .drain("t1", { stopAtEdited: true });

    expect(drained).toEqual([]);
    expect(
      useMessageQueueStore
        .getState()
        .getQueue("t1")
        .map((m) => m.content),
    ).toEqual(["a", "b"]);
  });

  it("drains the whole queue when nothing is being edited", () => {
    seed(["a", "b", "c"]);
    const drained = useMessageQueueStore
      .getState()
      .drain("t1", { stopAtEdited: true });
    expect(drained.map((m) => m.content)).toEqual(["a", "b", "c"]);
    expect(useMessageQueueStore.getState().getQueue("t1")).toEqual([]);
  });

  it("ignores the boundary without stopAtEdited, even mid-edit", () => {
    const queue = seed(["a", "b", "c"]);
    useMessageQueueStore.getState().setEditing("t1", queue[1].id);

    const drained = useMessageQueueStore.getState().drain("t1");

    expect(drained.map((m) => m.content)).toEqual(["a", "b", "c"]);
    expect(useMessageQueueStore.getState().getQueue("t1")).toEqual([]);
  });
});

describe("combineQueuedMessages", () => {
  function msg(
    content: string,
    attachments: PendingAttachment[],
  ): QueuedMessage {
    return { id: content, content, attachments };
  }

  it("joins text in order with a blank line and concatenates attachments", () => {
    const result = combineQueuedMessages([
      msg("first", [image("one")]),
      msg("second", []),
      msg("third", [image("two"), image("three")]),
    ]);
    expect(result.text).toBe("first\n\nsecond\n\nthird");
    expect(result.attachments.map((a) => a.id)).toEqual([
      "one",
      "two",
      "three",
    ]);
  });

  it("handles an empty list", () => {
    expect(combineQueuedMessages([])).toEqual({ text: "", attachments: [] });
  });
});
