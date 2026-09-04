import {
  CANVAS_V2_CHANNEL,
  CANVAS_V2_FRAME_TO_HOST_CHANNEL,
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

it("sends changed fields without serializing unchanged values", () => {
  const send = vi.fn();
  const frame = document.createElement("webview") as BoardWebviewElement;
  frame.send = send;
  const toJSON = vi.fn(() => ({ value: "unchanged" }));
  const previous = {
    schemaVersion: 1 as const,
    fragments: [],
    state: {
      unchanged: { toJSON },
      changed: 1,
      removed: true,
      equal: { value: 1 },
    },
  };
  const { result } = renderHook(() =>
    useBoardFrame({
      boardId: "board",
      frameElement: frame,
      theme: "light",
      queryClient: new QueryClient(),
      getSnapshot: () => previous,
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

  result.current.syncSnapshot(previous, {
    ...previous,
    state: {
      unchanged: previous.state.unchanged,
      changed: 2,
      equal: { value: 1 },
    },
  });

  expect(toJSON).not.toHaveBeenCalled();
  expect(send.mock.calls.map(([, message]) => message)).toEqual([
    { channel: CANVAS_V2_CHANNEL, type: "set-state", key: "changed", value: 2 },
    {
      channel: CANVAS_V2_CHANNEL,
      type: "set-state",
      key: "removed",
      value: null,
    },
  ]);
});
