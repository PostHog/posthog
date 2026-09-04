import {
  type BoardApi,
  BoardSyncClient,
} from "@posthog/core/canvas-v2/boardSync";
import type { CanvasV2LogEntry } from "@posthog/shared";
import { emptyCanvasV2Snapshot } from "@posthog/shared";
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useBoardCache } from "./useBoardCache";

const { write, host } = vi.hoisted(() => {
  const write = vi.fn().mockResolvedValue(undefined);
  return { write, host: { canvasV2Cache: { write: { mutate: write } } } };
});

vi.mock("@posthog/host-router/react", () => ({
  useHostTRPCClient: () => host,
}));

function entry(seq: number): CanvasV2LogEntry {
  return {
    seq,
    opId: `op-${seq}`,
    actor: { kind: "user", userId: 2 },
    createdAt: "2026-01-01T00:00:00.000Z",
    op: { type: "set_state", key: `key-${seq}`, value: seq },
  };
}

async function setup() {
  const api = {
    get: vi.fn<BoardApi["get"]>().mockResolvedValue({
      id: "board",
      name: "Board",
      channelId: "space",
      createdAt: "2026-01-01T00:00:00.000Z",
      updatedAt: "2026-01-01T00:00:00.000Z",
      snapshot: emptyCanvasV2Snapshot(),
      snapshotSeq: 0,
      headSeq: 1,
      opsAfterSnapshot: [entry(1)],
    }),
    opsSince: vi.fn<BoardApi["opsSince"]>().mockResolvedValue({
      headSeq: 1,
      results: [],
    }),
    appendOps: vi.fn<BoardApi["appendOps"]>(),
  };
  const client = new BoardSyncClient(api, "board", {
    now: () => 0,
  });
  await client.load();
  const hook = renderHook((state) => useBoardCache(state.boardId, state), {
    initialProps: client.getState(),
  });
  await tick();
  return { api, client, ...hook };
}

async function tick() {
  await act(() => vi.advanceTimersByTimeAsync(500));
}

describe("useBoardCache", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
  });
  afterEach(() => vi.useRealTimers());

  it.each(["poll", "stream"] as const)(
    "writes a rename but skips unchanged %s data",
    async (source) => {
      const { client, rerender } = await setup();
      const snapshot = client.getState().snapshot;
      for (let poll = 0; poll < 3; poll++) {
        if (source === "poll") await client.poll();
        else client.ingestStreamEntry(entry(1));
        rerender(client.getState());
        await tick();
      }
      expect(client.getState().snapshot).toBe(snapshot);
      expect(write).toHaveBeenCalledTimes(1);

      client.setName("Renamed board");
      rerender(client.getState());
      await tick();

      expect(write).toHaveBeenCalledTimes(2);
      expect(write.mock.lastCall?.[0].payload.name).toBe("Renamed board");
    },
  );

  it("waits for a missing operation before writing a new head", async () => {
    const { api, client, rerender } = await setup();
    api.opsSince.mockRejectedValue(new Error("Disconnected"));
    client.ingestStreamEntry(entry(3));
    rerender(client.getState());
    await tick();
    expect(write).toHaveBeenCalledTimes(1);

    api.opsSince.mockResolvedValue({ headSeq: 3, results: [entry(2)] });
    await client.poll();
    rerender(client.getState());
    await tick();

    expect(write).toHaveBeenCalledTimes(2);
    expect(write.mock.lastCall?.[0].payload).toMatchObject({
      headSeq: 3,
      snapshot: { state: { "key-1": 1, "key-2": 2, "key-3": 3 } },
    });
  });
});
