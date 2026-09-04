import {
  type CanvasV2AppendOpsResult,
  type CanvasV2Board,
  type CanvasV2LogEntry,
  emptyCanvasV2Snapshot,
  foldOps,
} from "@posthog/shared";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type BoardApi, BoardSyncClient } from "./boardSync";

function entry(seq: number): CanvasV2LogEntry {
  return {
    seq,
    opId: `op-${seq}`,
    actor: { kind: "user", userId: 2 },
    createdAt: "2026-01-01T00:00:00.000Z",
    op: { type: "set_state", key: `key-${seq}`, value: seq },
  };
}

function setup() {
  const board: CanvasV2Board = {
    id: "board",
    name: "Board",
    channelId: "space",
    createdAt: "2026-01-01T00:00:00.000Z",
    updatedAt: "2026-01-01T00:00:00.000Z",
    snapshot: emptyCanvasV2Snapshot(),
    snapshotSeq: 0,
    headSeq: 0,
    opsAfterSnapshot: [],
  };
  const api = {
    get: vi.fn<BoardApi["get"]>().mockResolvedValue(board),
    opsSince: vi.fn<BoardApi["opsSince"]>(),
    appendOps: vi.fn<BoardApi["appendOps"]>(),
  };
  const client = new BoardSyncClient(api, board.id, {
    actorUser: { userId: 1 },
    now: () => 0,
  });
  return { api, client, board };
}

describe("BoardSyncClient", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it.each([false, true])(
    "uses the accepted operation for a repeated ID with server snapshots %s",
    async (serverSnapshots) => {
      const { api, client, board } = setup();
      board.serverSnapshots = serverSnapshots;
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
    },
  );

  it("sends only operations when the server maintains snapshots", async () => {
    const { api, client, board } = setup();
    board.serverSnapshots = true;
    board.snapshot.state.large = "large".repeat(100_000);
    await client.load();
    api.appendOps.mockResolvedValue({
      headSeq: 1,
      results: [{ opId: "move", seq: 1 }],
    });
    client.applyLocal(
      [{ type: "update_fragment", id: "fragment", patch: { x: 1 } }],
      undefined,
      ["move"],
    );
    await client.flush();

    expect(api.appendOps.mock.calls[0][1].snapshot).toBeUndefined();
    expect(JSON.stringify(api.appendOps.mock.calls[0][1]).length).toBeLessThan(
      300,
    );
    expect(client.getState().pending).toHaveLength(0);
  });

  it("loads the saved snapshot when polling retries a failed initial load", async () => {
    const { api, client, board } = setup();
    board.snapshot = { ...board.snapshot, state: { saved: true } };
    board.snapshotSeq = board.headSeq = 5;
    api.get.mockRejectedValueOnce(new Error("Disconnected"));
    api.opsSince.mockResolvedValue({ headSeq: 5, results: [] });
    await client.load();
    expect(client.getState().status).toBe("error");

    await client.poll();

    expect(client.getState()).toMatchObject({
      name: "Board",
      status: "synced",
      snapshot: { state: { saved: true } },
    });
    expect(api.get).toHaveBeenCalledTimes(2);
  });

  it("keeps stream events received during the initial load without a second read", async () => {
    const { api, client, board } = setup();
    board.snapshot = { ...board.snapshot, state: { "key-1": 1 } };
    board.snapshotSeq = board.headSeq = 1;
    let finishLoad!: (board: CanvasV2Board) => void;
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
      const entries: CanvasV2LogEntry[] = [
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
      board.snapshotSeq = board.headSeq = 5;
      await client.load();
      expect(client.getState().snapshot.state).toEqual({
        saved: true,
        local: true,
      });
    },
  );

  it("does not send a full snapshot for each state edit", async () => {
    const { api, client } = setup();
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

    expect(
      api.appendOps.mock.calls.filter(([, input]) => input.snapshot),
    ).toHaveLength(1);
    expect(Object.keys(client.getState().snapshot.state)).toHaveLength(20);

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
        },
      },
    ]);
    await client.flush();

    const snapshot = api.appendOps.mock.lastCall?.[1].snapshot;
    expect(snapshot?.fragments[0].id).toBe("note");
    expect(Object.keys(snapshot?.state ?? {})).toHaveLength(20);
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

  it("flushes edits queued while a checkpoint is in flight", async () => {
    const { api, client } = setup();
    const sync = new BoardSyncClient(api, "board", {
      checkpointIntervalMs: 0,
    });
    await sync.load();
    api.opsSince.mockResolvedValue({ headSeq: 1, results: [entry(1)] });
    let finishCheckpoint!: (result: CanvasV2AppendOpsResult) => void;
    api.appendOps.mockReturnValueOnce(
      new Promise((resolve) => {
        finishCheckpoint = resolve;
      }),
    );
    await sync.poll();
    sync.applyLocal([{ type: "set_state", key: "mine", value: true }]);
    await vi.advanceTimersByTimeAsync(150);
    api.appendOps.mockImplementation(async (_id, input) => ({
      headSeq: 2,
      results: input.ops.map(({ opId }) => ({ opId, seq: 2 })),
    }));

    finishCheckpoint({ headSeq: 1, results: [] });
    await vi.advanceTimersByTimeAsync(150);

    expect(sync.getState().pending).toEqual([]);
    expect(sync.getState().snapshot.state).toEqual({
      "key-1": 1,
      mine: true,
    });
    client.stop();
    sync.stop();
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
    const client = new BoardSyncClient(api, "board", { now: () => 0 });
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
    expect(api.appendOps.mock.lastCall?.[1].snapshot).toBeUndefined();
  });

  it("saves remaining edits when the board closes during an append", async () => {
    const { api, client } = setup();
    await client.load();
    let finishAppend!: (result: CanvasV2AppendOpsResult) => void;
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
});
