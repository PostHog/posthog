import {
  CANVAS_V2_CHANNEL,
  CANVAS_V2_FRAME_TO_HOST_CHANNEL,
  CANVAS_V2_HOST_TO_FRAME_CHANNEL,
  type CanvasV2DataMethod,
  type CanvasV2Snapshot,
  emptyCanvasV2Snapshot,
} from "@posthog/shared";
import { QueryClient } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { BoardWebviewElement } from "./boardFrameElement";
import { useBoardFrame } from "./useBoardFrame";

vi.mock("@posthog/ui/shell/useHostCapabilities", () => ({
  useHostCapabilities: () => ({ vendoredCanvasModules: false }),
}));

vi.mock("@posthog/ui/features/canvas-v2/runtime/canvasV2DataBridge", () => ({
  spendBoardWrite: vi.fn(),
  handleCanvasV2DataRequest: vi.fn(),
}));

function mountFrame(snapshot: CanvasV2Snapshot) {
  const send = vi.fn();
  const frame = document.createElement("webview") as BoardWebviewElement;
  frame.send = send;
  const { result } = renderHook(() =>
    useBoardFrame({
      boardId: "board",
      frameElement: frame,
      theme: "light",
      queryClient: new QueryClient(),
      getSnapshot: () => snapshot,
      applyLocal: vi.fn(),
      reportCaret: vi.fn(),
      events: {
        onExitFocus: vi.fn(),
        onReady: vi.fn(),
        onFragmentRendered: vi.fn(),
        onFragmentError: vi.fn(),
        onStateChanged: vi.fn(),
        onWheel: vi.fn(),
        onBackgroundPointer: vi.fn(),
        onFragmentPointerDown: vi.fn(),
        onPointerMove: vi.fn(),
        onPointerLeave: vi.fn(),
      },
    }),
  );
  act(() =>
    frame.dispatchEvent(
      Object.assign(new Event("ipc-message"), {
        channel: CANVAS_V2_FRAME_TO_HOST_CHANNEL,
        args: [{ channel: CANVAS_V2_CHANNEL, type: "ready" }],
      }),
    ),
  );
  send.mockClear();
  return { frame, send, result };
}

it("sends changed data without repeating unchanged source or state", () => {
  const toJSON = vi.fn(() => ({ value: "unchanged" }));
  const fragment = {
    id: "moved",
    x: 0,
    y: 0,
    w: 360,
    h: 240,
    z: 0,
    code: "export default () => null",
    codeVersion: 1,
  };
  const previous = {
    schemaVersion: 1 as const,
    fragments: [
      fragment,
      { ...fragment, id: "edited" },
      { ...fragment, id: "removed" },
    ],
    state: {
      unchanged: { toJSON },
      changed: 1,
      removed: true,
      equal: { value: 1 },
    },
  };
  const { send, result } = mountFrame(previous);

  result.current.syncSnapshot(previous, {
    ...previous,
    fragments: [
      { ...fragment, x: 100 },
      {
        ...fragment,
        id: "edited",
        code: "export default () => 'new'",
        codeVersion: 2,
      },
      { ...fragment, id: "added" },
    ],
    state: {
      unchanged: previous.state.unchanged,
      changed: 2,
      equal: { value: 1 },
    },
  });

  expect(toJSON).not.toHaveBeenCalled();
  expect(send.mock.calls.map(([, message]) => message)).toEqual([
    {
      channel: CANVAS_V2_CHANNEL,
      type: "upsert-fragment",
      fragment: { ...fragment, x: 100, code: undefined },
    },
    {
      channel: CANVAS_V2_CHANNEL,
      type: "upsert-fragment",
      fragment: {
        ...fragment,
        id: "edited",
        code: "export default () => 'new'",
        codeVersion: 2,
      },
    },
    {
      channel: CANVAS_V2_CHANNEL,
      type: "upsert-fragment",
      fragment: { ...fragment, id: "added" },
    },
    { channel: CANVAS_V2_CHANNEL, type: "remove-fragment", id: "removed" },
    { channel: CANVAS_V2_CHANNEL, type: "set-state", key: "changed", value: 2 },
    {
      channel: CANVAS_V2_CHANNEL,
      type: "set-state",
      key: "removed",
      value: null,
    },
  ]);
});

it.each<[CanvasV2DataMethod, number, boolean]>([
  ["stateEditText", 20_000, true],
  ["stateEditText", 60_000, false],
  ["query", 20_000, false],
])("bounds %s requests with %i entry IDs", async (method, count, ok) => {
  const { frame, send } = mountFrame(emptyCanvasV2Snapshot());
  await act(async () => {
    frame.dispatchEvent(
      Object.assign(new Event("ipc-message"), {
        channel: CANVAS_V2_FRAME_TO_HOST_CHANNEL,
        args: [
          {
            channel: CANVAS_V2_CHANNEL,
            type: "data-request",
            id: "request",
            method,
            payload: {
              key: "note",
              base: "a".repeat(count),
              next: "b".repeat(count),
              baseIds: Array.from(
                { length: count },
                (_, index) => `${"a".repeat(32)}-${index}`,
              ),
            },
          },
        ],
      }),
    );
  });
  expect(send).toHaveBeenCalledWith(
    CANVAS_V2_HOST_TO_FRAME_CHANNEL,
    expect.objectContaining({
      type: "data-response",
      id: "request",
      ok,
    }),
  );
});
