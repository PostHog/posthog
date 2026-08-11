import { createElement } from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useMicPressHandlers } from "./useMicPressHandlers";

type Handlers = ReturnType<typeof useMicPressHandlers>;

function renderHandlers(args: {
  isRecording?: boolean;
  isTranscribing?: boolean;
  holdToRecordEnabled?: boolean;
}) {
  const startRecording = vi.fn(() => Promise.resolve());
  const stopRecording = vi.fn(() => Promise.resolve());
  const cancelRecording = vi.fn(() => Promise.resolve());
  let handlers: Handlers | null = null;

  function Harness(props: {
    isRecording: boolean;
    isTranscribing: boolean;
    holdToRecordEnabled: boolean;
  }) {
    handlers = useMicPressHandlers({
      ...props,
      startRecording,
      stopRecording,
      cancelRecording,
    });
    return null;
  }

  const props = {
    isRecording: args.isRecording ?? false,
    isTranscribing: args.isTranscribing ?? false,
    holdToRecordEnabled: args.holdToRecordEnabled ?? true,
  };
  let renderer: ReactTestRenderer;
  act(() => {
    renderer = create(createElement(Harness, props));
  });
  return {
    handlers: () => {
      if (!handlers) throw new Error("harness did not render");
      return handlers;
    },
    update: (next: Partial<typeof props>) =>
      act(() => {
        renderer.update(createElement(Harness, { ...props, ...next }));
      }),
    startRecording,
    stopRecording,
    cancelRecording,
    unmount: () => renderer.unmount(),
  };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useMicPressHandlers", () => {
  it("hold starts recording and release stops it", async () => {
    const h = renderHandlers({});

    await act(() => h.handlers().onMicLongPress());
    expect(h.startRecording).toHaveBeenCalledOnce();

    await act(() => h.handlers().onMicPressOut());
    expect(h.stopRecording).toHaveBeenCalledOnce();
  });

  it("release without a hold does nothing", async () => {
    const h = renderHandlers({});

    await act(() => h.handlers().onMicPressOut());

    expect(h.stopRecording).not.toHaveBeenCalled();
  });

  it("long-pressing a tap-started recording cancels instead of restarting", async () => {
    const h = renderHandlers({ isRecording: true });

    await act(() => h.handlers().onMicLongPress());

    expect(h.cancelRecording).toHaveBeenCalledOnce();
    expect(h.startRecording).not.toHaveBeenCalled();

    await act(() => h.handlers().onMicPressOut());
    expect(h.stopRecording).not.toHaveBeenCalled();
  });

  it("hold does not start recording when the button is not a mic", async () => {
    const h = renderHandlers({ holdToRecordEnabled: false });

    await act(() => h.handlers().onMicLongPress());

    expect(h.startRecording).not.toHaveBeenCalled();
  });

  it("tap toggles: starts when idle, stops when recording", async () => {
    const h = renderHandlers({});
    await act(() => h.handlers().onMicPress());
    expect(h.startRecording).toHaveBeenCalledOnce();

    h.update({ isRecording: true });
    await act(() => h.handlers().onMicPress());
    expect(h.stopRecording).toHaveBeenCalledOnce();
  });
});
