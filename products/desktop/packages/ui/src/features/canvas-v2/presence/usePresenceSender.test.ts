import type { CanvasV2PresenceInput } from "@posthog/shared";
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { usePresenceSender } from "./usePresenceSender";

const { mutate } = vi.hoisted(() => ({
  mutate:
    vi.fn<
      (input: { id: string; presence: CanvasV2PresenceInput }) => Promise<void>
    >(),
}));
vi.mock("@posthog/host-router/react", () => ({
  useHostTRPCClient: () => ({ canvasV2Stream: { sendPresence: { mutate } } }),
}));

describe("usePresenceSender", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(10_000);
    mutate.mockReset().mockResolvedValue(undefined);
  });
  afterEach(() => vi.useRealTimers());

  it("keeps one request in flight and sends only the latest pending position", async () => {
    let finish!: () => void;
    mutate.mockReturnValueOnce(
      new Promise<void>((resolve) => {
        finish = resolve;
      }),
    );
    const { result, unmount } = renderHook(() => usePresenceSender("board"));
    act(() => result.current.reportCursor({ x: 1.2, y: 2.8 }));
    act(() => {
      for (let x = 2; x <= 1000; x++) result.current.reportCursor({ x, y: 0 });
      result.current.reportSelection(
        Array.from({ length: 100 }, (_, index) => `fragment-${index}`),
      );
    });
    await act(() => vi.advanceTimersByTimeAsync(1000));
    expect(mutate).toHaveBeenCalledTimes(1);
    expect(mutate.mock.calls[0][0].presence.cursor).toEqual({ x: 1, y: 3 });

    await act(async () => {
      finish();
    });

    expect(mutate).toHaveBeenCalledTimes(2);
    expect(mutate.mock.calls[1][0].presence.cursor).toEqual({ x: 1000, y: 0 });
    expect(mutate.mock.calls[1][0].presence.selectedIds).toHaveLength(50);
    act(() => result.current.reportCursor(null));
    await act(() => vi.advanceTimersByTimeAsync(99));
    expect(mutate).toHaveBeenCalledTimes(2);
    await act(() => vi.advanceTimersByTimeAsync(1));
    expect(mutate).toHaveBeenCalledTimes(3);
    expect(mutate.mock.calls[2][0].presence.cursor).toBeNull();
    act(() => result.current.reportSelection(["pending"]));
    unmount();
    await act(() => vi.advanceTimersByTimeAsync(1000));
    expect(mutate).toHaveBeenCalledTimes(3);
  });

  it("does not send old presence or resume an old request on another board", async () => {
    let fail!: (reason: Error) => void;
    mutate.mockReturnValueOnce(
      new Promise<void>((_resolve, reject) => {
        fail = reject;
      }),
    );
    const { result, rerender, unmount } = renderHook(
      ({ boardId }) => usePresenceSender(boardId),
      { initialProps: { boardId: "first" } },
    );
    act(() => result.current.reportCursor({ x: 1, y: 2 }));
    act(() => result.current.reportSelection(["old"]));
    rerender({ boardId: "second" });
    act(() => result.current.reportCursor({ x: 3, y: 4 }));
    await act(async () => {
      fail(new Error("Disconnected"));
    });
    await act(() => vi.advanceTimersByTimeAsync(1000));

    expect(mutate).toHaveBeenCalledTimes(2);
    expect(mutate.mock.calls[1][0]).toMatchObject({
      id: "second",
      presence: {
        cursor: { x: 3, y: 4 },
        selectedIds: [],
        viewport: null,
        carets: [],
      },
    });
    unmount();
  });
});
