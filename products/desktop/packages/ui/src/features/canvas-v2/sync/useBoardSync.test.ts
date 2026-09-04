import type { BoardApi } from "@posthog/core/canvas-v2/boardSync";
import { emptyCanvasV2Snapshot } from "@posthog/shared";
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type BoardSyncActorUser, useBoardSync } from "./useBoardSync";

function setup() {
  let seq = 0;
  const api = {
    get: vi.fn<BoardApi["get"]>().mockImplementation(async (id) => ({
      id,
      name: id,
      channelId: "space",
      createdAt: "2026-01-01T00:00:00.000Z",
      updatedAt: "2026-01-01T00:00:00.000Z",
      snapshot: emptyCanvasV2Snapshot(),
      snapshotSeq: 0,
      headSeq: 0,
      opsAfterSnapshot: [],
    })),
    opsSince: vi
      .fn<BoardApi["opsSince"]>()
      .mockResolvedValue({ headSeq: 0, results: [] }),
    appendOps: vi
      .fn<BoardApi["appendOps"]>()
      .mockImplementation(async (_id, input) => {
        const results = input.ops.map(({ opId }) => ({ opId, seq: ++seq }));
        return { headSeq: seq, results };
      }),
  };
  const render = vi.fn();
  const initialProps: { boardId: string; actorUser?: BoardSyncActorUser } = {
    boardId: "first",
  };
  const hook = renderHook(
    ({ boardId, actorUser }) => {
      render();
      return useBoardSync(boardId, api, actorUser);
    },
    { initialProps },
  );
  return { api, render, ...hook };
}

describe("useBoardSync", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("uses a late user identity without reloading or losing pending edits", async () => {
    const { api, result, rerender } = setup();
    await act(() => vi.advanceTimersByTimeAsync(0));
    const client = result.current.client;
    act(() =>
      client.applyLocal([{ type: "set_state", key: "first", value: true }]),
    );

    rerender({
      boardId: "first",
      actorUser: { userId: 7, userName: "Test user" },
    });
    act(() =>
      result.current.client.applyLocal([
        { type: "set_state", key: "second", value: true },
      ]),
    );

    expect(result.current.client).toBe(client);
    expect(api.get).toHaveBeenCalledTimes(1);
    expect(result.current.state.pending).toHaveLength(2);
    expect(result.current.state.pending[1].actor.userId).toBe(7);
    await act(() => client.flush());
  });

  it("does not render updates from a previous board", async () => {
    const { result, rerender, render } = setup();
    await act(() => vi.advanceTimersByTimeAsync(0));
    const previous = result.current.client;
    rerender({ boardId: "second" });
    await act(() => vi.advanceTimersByTimeAsync(0));
    const renders = render.mock.calls.length;

    act(() => previous.setName("Late update"));

    expect(render).toHaveBeenCalledTimes(renders);
    expect(result.current.state).toMatchObject({
      boardId: "second",
      name: "second",
    });
  });
});
