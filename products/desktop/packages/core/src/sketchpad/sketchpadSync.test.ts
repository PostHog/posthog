import {
  type AcpMessage,
  emptySketchpadSnapshot,
  foldOps,
  type Sketchpad,
  type SketchpadAppendOpsResult,
  type SketchpadLogEntry,
} from "@posthog/shared";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type SketchpadApi, SketchpadSyncClient } from "./sketchpadSync";
import { applySketchpadToolCalls } from "./toolCallEvents";

function entry(seq: number): SketchpadLogEntry {
  return {
    seq,
    opId: `op-${seq}`,
    actor: { kind: "user", userId: 2 },
    createdAt: "2026-01-01T00:00:00.000Z",
    op: { type: "set_state", key: `key-${seq}`, value: seq },
  };
}

function setup() {
  const board: Sketchpad = {
    id: "board",
    name: "Sketchpad",
    channelId: "space",
    createdAt: "2026-01-01T00:00:00.000Z",
    updatedAt: "2026-01-01T00:00:00.000Z",
    snapshot: emptySketchpadSnapshot(),
    headSeq: 0,
  };
  const api = {
    get: vi.fn<SketchpadApi["get"]>().mockResolvedValue(board),
    opsSince: vi.fn<SketchpadApi["opsSince"]>(),
    appendOps: vi.fn<SketchpadApi["appendOps"]>(),
  };
  const client = new SketchpadSyncClient(api, board.id, {
    actorUser: { userId: 1 },
    now: () => 0,
  });
  return { api, client, board };
}

describe("SketchpadSyncClient", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("polls only while running and can restart after stopping", async () => {
    const { api, client } = setup();
    api.opsSince.mockResolvedValue({ headSeq: 0, results: [] });
    await client.load();
    await vi.advanceTimersByTimeAsync(10_000);
    expect(api.opsSince).not.toHaveBeenCalled();
    client.start();
    await vi.advanceTimersByTimeAsync(10_000);
    const reads = api.opsSince.mock.calls.length;
    expect(reads).toBeGreaterThan(0);
    client.stop();
    await vi.advanceTimersByTimeAsync(10_000);
    expect(api.opsSince).toHaveBeenCalledTimes(reads);
    client.start();
    await vi.advanceTimersByTimeAsync(10_000);
    expect(api.opsSince.mock.calls.length).toBeGreaterThan(reads);
    client.stop();
  });

  it("applies agent operations once without reading completed fragment code again", async () => {
    const { client } = setup();
    await client.load();
    const code = vi.fn(() => "export default () => null");
    const calls = [
      [
        "add_fragment",
        {
          id: "note",
          get code() {
            return code();
          },
        },
      ],
      ["update_fragment", { id: "note", patch: { x: 42 } }],
      ["set_state", { key: "count", value: 3 }],
      ["remove_fragment", { id: "note" }],
    ] as const;
    const events: AcpMessage[] = calls.map(([tool, rawInput], index) => ({
      type: "acp_message",
      ts: 0,
      message: {
        jsonrpc: "2.0",
        method: "session/update",
        params: {
          update: {
            sessionUpdate: "tool_call",
            toolCallId: `call-${index}`,
            status: "completed",
            rawInput,
            _meta: {
              claudeCode: {
                toolName: `mcp__posthog-code-tools__sketchpad_${tool}`,
              },
            },
          },
        },
      },
    }));
    const added = vi.fn();
    applySketchpadToolCalls(events, client, "task", added);
    applySketchpadToolCalls(events, client, "task", added);
    expect(client.getState().pending.map(({ op }) => op.type)).toEqual(
      calls.map(([tool]) => tool),
    );
    expect(client.getState().snapshot).toEqual({
      schemaVersion: 1,
      fragments: [],
      state: { count: 3 },
    });
    expect(added).toHaveBeenCalledExactlyOnceWith("note");
    expect(code).toHaveBeenCalledTimes(1);
  });

  it("uses the accepted operation for a repeated ID", async () => {
    const { api, client } = setup();
    await client.load();
    const accepted = entry(1);
    api.appendOps.mockResolvedValue({
      headSeq: 1,
      results: [{ opId: accepted.opId, seq: 1 }],
      replayed: [accepted],
    });
    client.applyLocal(
      [{ type: "set_state", key: "key-1", value: "different local value" }],
      { kind: "agent", taskId: "task" },
      [accepted.opId],
    );
    await client.flush();
    client.ingestStreamEntry(accepted);

    expect(client.getState()).toMatchObject({
      status: "synced",
      pending: [],
      snapshot: { state: { "key-1": 1 } },
    });
    expect(api.get).toHaveBeenCalledTimes(1);
    expect(api.opsSince).not.toHaveBeenCalled();
    expect(client.getState().log[0].actor).toEqual(accepted.actor);
  });

  it("loads the saved snapshot when polling retries a failed initial load", async () => {
    const { api, client, board } = setup();
    board.snapshot = { ...board.snapshot, state: { saved: true } };
    board.headSeq = 5;
    api.get.mockRejectedValueOnce(new Error("Disconnected"));
    api.opsSince.mockResolvedValue({ headSeq: 5, results: [] });
    await client.load();
    expect(client.getState().status).toBe("error");

    await client.poll();

    expect(client.getState()).toMatchObject({
      name: "Sketchpad",
      status: "synced",
      snapshot: { state: { saved: true } },
    });
    expect(api.get).toHaveBeenCalledTimes(2);
  });

  it("keeps stream events received during the initial load without a second read", async () => {
    const { api, client, board } = setup();
    board.snapshot = { ...board.snapshot, state: { "key-1": 1 } };
    board.headSeq = 1;
    let finishLoad!: (board: Sketchpad) => void;
    api.get.mockReturnValueOnce(
      new Promise((resolve) => {
        finishLoad = resolve;
      }),
    );
    api.opsSince.mockResolvedValue({ headSeq: 2, results: [entry(2)] });
    const loading = client.load();
    client.ingestStreamEntry(entry(2));
    client.setLive(true);
    await vi.advanceTimersByTimeAsync(0);
    finishLoad(board);
    await loading;

    expect(client.getState()).toMatchObject({
      headSeq: 2,
      status: "synced",
      snapshot: { state: { "key-1": 1, "key-2": 2 } },
    });
    expect(api.opsSince).not.toHaveBeenCalled();
  });

  it("retries a stream gap without another event and stops polling after repair", async () => {
    const { api, client } = setup();
    await client.load();
    api.opsSince.mockResolvedValue({ headSeq: 0, results: [] });
    client.start();
    client.setLive(true);
    await vi.advanceTimersByTimeAsync(0);
    api.opsSince.mockRejectedValueOnce(new Error("Disconnected"));
    client.ingestStreamEntry(entry(3));
    await vi.advanceTimersByTimeAsync(0);
    api.opsSince.mockResolvedValue({
      headSeq: 3,
      results: [entry(1), entry(2)],
    });

    await vi.advanceTimersByTimeAsync(1500);

    expect(client.getState()).toMatchObject({
      status: "synced",
      snapshot: { state: { "key-1": 1, "key-2": 2, "key-3": 3 } },
    });
    const reads = api.opsSince.mock.calls.length;
    await vi.advanceTimersByTimeAsync(3000);
    expect(api.opsSince).toHaveBeenCalledTimes(reads);
    client.stop();
  });

  it.each(["poll", "stream"] as const)(
    "fills every gap after a %s reports a newer head",
    async (source) => {
      const { api, client } = setup();
      await client.load();
      api.opsSince.mockImplementation(async (_id, since) => ({
        headSeq: 3,
        results: since < 3 ? [entry(since + 1)] : [],
      }));
      if (source === "stream") client.ingestStreamEntry(entry(3));

      await client.poll();
      await vi.advanceTimersByTimeAsync(0);

      expect(client.getState().snapshot.state).toEqual({
        "key-1": 1,
        "key-2": 2,
        "key-3": 3,
      });
      expect(client.getState().logComplete).toBe(true);
    },
  );

  it("keeps concurrent edits when an append follows another writer", async () => {
    const { api, client } = setup();
    await client.load();
    client.applyLocal([{ type: "set_state", key: "mine", value: true }]);
    api.appendOps.mockImplementation(async (_id, input) => ({
      headSeq: 2,
      results: input.ops.map(({ opId }) => ({ opId, seq: 2 })),
    }));
    api.opsSince.mockImplementation(async (_id, since) => ({
      headSeq: 2,
      results: since === 0 ? [entry(1)] : [],
    }));

    await client.flush();
    await client.poll();

    expect(client.getState().snapshot.state).toEqual({
      "key-1": 1,
      mine: true,
    });
    expect(client.getState().pending).toEqual([]);
  });

  it.each([
    [2, 3],
    [3, 2],
  ])(
    "keeps unchanged fields after remote edits arrive as %s, %s",
    async (first, second) => {
      const { api, client, board } = setup();
      await client.load();
      api.opsSince.mockRejectedValue(new Error("Disconnected"));
      const entries: SketchpadLogEntry[] = [
        {
          ...entry(1),
          op: {
            type: "edit_field",
            key: "text",
            kind: "text",
            insert: [{ id: "a", k: "a", v: "a" }],
          },
        },
        entry(2),
        {
          ...entry(3),
          op: {
            type: "edit_field",
            key: "text",
            kind: "text",
            insert: [{ id: "b", k: "b", v: "b" }],
          },
        },
      ];
      client.ingestStreamEntry(entries[0]);
      client.applyLocal([{ type: "set_state", key: "local", value: true }]);
      client.ingestStreamEntry(entries[first - 1]);
      client.ingestStreamEntry(entries[second - 1]);
      expect(client.getState().snapshot).toEqual({
        ...foldOps(board.snapshot, entries),
        state: { ...foldOps(board.snapshot, entries).state, local: true },
      });
      const text = client.getState().snapshot.state.text;

      client.ingestStreamEntry(entry(4));

      expect(client.getState().snapshot.state.text).toBe(text);
      board.snapshot = { ...board.snapshot, state: { saved: true } };
      board.headSeq = 5;
      await client.load();
      expect(client.getState().snapshot.state).toEqual({
        saved: true,
        local: true,
      });
    },
  );

  it("sends only operations when editing a large board", async () => {
    const { api, client, board } = setup();
    board.snapshot.state.large = "large".repeat(100_000);
    await client.load();
    let seq = 0;
    api.appendOps.mockImplementation(async (_id, input) => ({
      results: input.ops.map(({ opId }) => ({ opId, seq: ++seq })),
      headSeq: seq,
    }));
    for (let index = 1; index <= 20; index++) {
      client.applyLocal([entry(index).op]);
      await client.flush();
    }

    client.applyLocal([
      {
        type: "add_fragment",
        fragment: {
          id: "note",
          x: 0,
          y: 0,
          w: 360,
          h: 240,
          z: 0,
          code: "export default () => null",
          codeVersion: 1,
          surface: "card",
          hidden: false,
        },
      },
      { type: "update_fragment", id: "note", patch: { x: 1 } },
    ]);
    await client.flush();

    for (const [, input] of api.appendOps.mock.calls) {
      expect(input).not.toHaveProperty("snapshot");
      expect(JSON.stringify(input).length).toBeLessThan(600);
    }
    expect(client.getState().snapshot.fragments[0]).toMatchObject({
      id: "note",
      x: 1,
    });
    expect(Object.keys(client.getState().snapshot.state)).toHaveLength(21);
    expect(client.getState().pending).toHaveLength(0);
  });

  it("loads older history despite having a newer snapshot and stream entries", async () => {
    const { api, client, board } = setup();
    board.headSeq = 3;
    await client.load();
    client.ingestStreamEntry(entry(3));
    client.ingestStreamEntry(entry(1));
    api.opsSince.mockResolvedValue({
      results: [entry(2), entry(3)],
      headSeq: 3,
    });
    await client.loadFullLog();
    expect(api.opsSince).toHaveBeenCalledWith("board", 1, 1000);
    expect(client.getState().log.map(({ seq }) => seq)).toEqual([1, 2, 3]);
    expect(client.getState().logComplete).toBe(true);
  });

  it("does not offer a partial history for restore", async () => {
    const { api, client } = setup();
    await client.load();
    api.opsSince.mockRejectedValue(new Error("Disconnected"));
    client.ingestStreamEntry(entry(3));
    client.ingestStreamEntry(entry(1));

    expect(client.getState().logComplete).toBe(false);
    await client.restoreTo(2);
    expect(client.getState().pending).toEqual([]);
  });

  it("keeps a submitted operation unchanged after a lost response", async () => {
    const { api, client } = setup();
    await client.load();
    const edit = (id: string) => ({
      type: "edit_field" as const,
      key: "text",
      kind: "text" as const,
      insert: [{ id, k: id, v: id }],
    });
    client.applyLocal([edit("a")]);
    api.appendOps.mockRejectedValueOnce(new Error("Response lost"));
    await client.flush();
    const submitted = api.appendOps.mock.calls[0][1].ops[0];

    client.applyLocal([edit("b")]);

    expect(
      client.getState().pending.map(({ opId, op }) => ({ opId, op })),
    ).toEqual([submitted, { opId: expect.any(String), op: edit("b") }]);
  });

  it("does not undo another user's edit when the current user is unknown", async () => {
    const { api } = setup();
    const client = new SketchpadSyncClient(api, "board", { now: () => 0 });
    await client.load();
    client.ingestStreamEntry(entry(1));

    await client.undoLastOwnOp();

    expect(client.getState().pending).toEqual([]);
    expect(client.getState().snapshot.state).toEqual({ "key-1": 1 });
  });

  it("continues to the previous edit on each undo", async () => {
    const { api, client } = setup();
    await client.load();
    let seq = 0;
    api.appendOps.mockImplementation(async (_id, input) => {
      const results = input.ops.map(({ opId }) => ({ opId, seq: ++seq }));
      return { headSeq: seq, results };
    });
    client.applyLocal([entry(1).op]);
    await client.flush();
    client.applyLocal([entry(2).op]);
    await client.flush();
    client.ingestStreamEntry(entry(++seq));

    await client.undoLastOwnOp();
    expect(client.getState().snapshot.state).toEqual({
      "key-1": 1,
      "key-3": 3,
    });
    await client.undoLastOwnOp();
    expect(client.getState().snapshot.state).toEqual({ "key-3": 3 });
    await client.flush();
    expect(api.appendOps.mock.lastCall?.[1].ops[0].op.type).toBe("restore");
    expect(api.appendOps.mock.lastCall?.[1]).not.toHaveProperty("snapshot");
  });

  it("saves remaining edits when the board closes during an append", async () => {
    const { api, client } = setup();
    await client.load();
    let finishAppend!: (result: SketchpadAppendOpsResult) => void;
    api.appendOps.mockReturnValueOnce(
      new Promise((resolve) => {
        finishAppend = resolve;
      }),
    );
    client.applyLocal([entry(1).op]);
    const firstSave = client.flush();
    const firstId = api.appendOps.mock.calls[0][1].ops[0].opId;
    client.applyLocal([entry(2).op]);
    client.stop();
    api.appendOps.mockImplementation(async (_id, input) => ({
      headSeq: 2,
      results: input.ops.map(({ opId }) => ({ opId, seq: 2 })),
    }));

    finishAppend({ headSeq: 1, results: [{ opId: firstId, seq: 1 }] });
    await firstSave;
    await vi.advanceTimersByTimeAsync(150);

    expect(client.getState().pending).toEqual([]);
    expect(client.getState().snapshot.state).toEqual({
      "key-1": 1,
      "key-2": 2,
    });
  });

  it("recovers offline edits with their original operation IDs after reopening", async () => {
    const { api } = setup();
    let saved: string | null = null;
    const pendingStorage = {
      key: "board",
      storage: {
        getItem: () => saved,
        setItem: (_key: string, value: string) => {
          saved = value;
        },
        removeItem: () => {
          saved = null;
        },
      },
    };
    const first = new SketchpadSyncClient(api, "board", { pendingStorage });
    await first.load();
    first.applyLocal([entry(1).op]);
    api.appendOps.mockRejectedValue(new Error("Offline"));
    await first.flush();
    const original = first.getState().pending[0];
    first.stop();
    await Promise.resolve();

    const reopened = new SketchpadSyncClient(api, "board", { pendingStorage });
    await reopened.load();
    expect(reopened.getState().pending).toEqual([original]);
    api.appendOps.mockResolvedValue({
      headSeq: 1,
      results: [{ opId: original.opId, seq: 1 }],
    });
    await reopened.flush();
    expect(api.appendOps.mock.lastCall?.[1].ops).toEqual([
      { opId: original.opId, op: original.op },
    ]);
    expect(saved).toBe("[]");
  });

  it("keeps later edits when a restore becomes stale before it is sent", async () => {
    const { api, client, board } = setup();
    await client.load();
    client.applyLocal([
      { type: "restore", toSeq: 0, snapshot: emptySketchpadSnapshot() },
    ]);
    client.ingestStreamEntry(entry(1));
    client.applyLocal([{ type: "set_state", key: "later", value: true }]);
    board.snapshot = foldOps(board.snapshot, [entry(1)]);
    board.headSeq = 1;
    api.appendOps.mockRejectedValueOnce({
      data: { httpStatus: 400 },
      message: "Sketchpad changed",
    });
    await client.flush();
    expect(api.appendOps.mock.calls[0][1].ops).toHaveLength(1);
    expect(api.appendOps.mock.calls[0][1].ops[0].op).toMatchObject({
      expectedSeq: 0,
    });
    api.appendOps.mockImplementationOnce(async (_id, input) => ({
      headSeq: 2,
      results: [{ opId: input.ops[0].opId, seq: 2 }],
    }));
    await client.flush();
    expect(client.getState().snapshot.state).toEqual({
      "key-1": 1,
      later: true,
    });
    expect(client.getState().pending).toEqual([]);
  });
});
