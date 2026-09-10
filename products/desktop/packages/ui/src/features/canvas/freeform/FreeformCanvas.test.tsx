import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FreeformCanvas } from "./FreeformCanvas";

vi.mock("@posthog/ui/shell/openExternal", () => ({
  openExternalUrl: vi.fn(),
}));

const renderCanvas = () => {
  render(
    <FreeformCanvas
      code="export default function Canvas() { return null }"
      onDataRequest={vi.fn()}
    />,
  );
  return screen.getByTitle("Canvas") as HTMLIFrameElement;
};

const postFromCanvas = (iframe: HTMLIFrameElement, url: string) => {
  window.dispatchEvent(
    new MessageEvent("message", {
      data: { channel: "posthog-canvas", type: "open-external", url },
      source: iframe.contentWindow,
    }),
  );
};

describe("FreeformCanvas", () => {
  it("does not grant the sandbox popup permission", () => {
    renderCanvas();

    expect(screen.getByTitle("Canvas")).toHaveAttribute(
      "sandbox",
      "allow-scripts",
    );
  });

  it("forwards a validated text selection in viewport coordinates", () => {
    const onTextSelection = vi.fn();
    render(
      <FreeformCanvas
        code="export default function Canvas() { return null }"
        onDataRequest={vi.fn()}
        onTextSelection={onTextSelection}
      />,
    );
    const iframe = screen.getByTitle("Canvas") as HTMLIFrameElement;
    vi.spyOn(iframe, "getBoundingClientRect").mockReturnValue({
      top: 100,
      left: 200,
      right: 800,
      bottom: 700,
      width: 600,
      height: 600,
      x: 200,
      y: 100,
      toJSON: () => ({}),
    });

    window.dispatchEvent(
      new MessageEvent("message", {
        source: iframe.contentWindow,
        data: {
          channel: "posthog-canvas",
          type: "text-selection",
          selection: {
            quote: "selected text",
            prefix: "before ",
            suffix: " after",
            start: 7,
            end: 20,
            rect: { top: 10, right: 80, bottom: 30, left: 20 },
          },
        },
      }),
    );

    expect(onTextSelection).toHaveBeenCalledWith(
      expect.objectContaining({
        quote: "selected text",
        rect: { top: 110, right: 280, bottom: 130, left: 220 },
      }),
    );

    window.dispatchEvent(
      new MessageEvent("message", {
        source: iframe.contentWindow,
        data: {
          channel: "posthog-canvas",
          type: "text-selection-cleared",
        },
      }),
    );
    expect(onTextSelection).toHaveBeenLastCalledWith(null);
  });

  it("forwards persisted comment highlights into the running sandbox", () => {
    const highlight = {
      id: "comment-1",
      active: false,
      anchor: {
        quote: "selected text",
        prefix: "before ",
        suffix: " after",
        start: 7,
        end: 20,
      },
    };
    const { rerender } = render(
      <FreeformCanvas
        code="export default function Canvas() { return null }"
        onDataRequest={vi.fn()}
        commentHighlights={[]}
      />,
    );
    const iframe = screen.getByTitle("Canvas") as HTMLIFrameElement;
    const postMessage = vi.spyOn(iframe.contentWindow as Window, "postMessage");
    fireEvent.load(iframe);
    postMessage.mockClear();

    rerender(
      <FreeformCanvas
        code="export default function Canvas() { return null }"
        onDataRequest={vi.fn()}
        commentHighlights={[highlight]}
      />,
    );

    expect(postMessage).toHaveBeenCalledWith(
      {
        channel: "posthog-canvas",
        type: "set-comment-highlights",
        highlights: [highlight],
      },
      "*",
    );
  });

  it("clears native iframe selection when the host dismisses it", () => {
    const { rerender } = render(
      <FreeformCanvas
        code="export default function Canvas() { return null }"
        onDataRequest={vi.fn()}
        clearTextSelectionKey={0}
      />,
    );
    const iframe = screen.getByTitle("Canvas") as HTMLIFrameElement;
    const postMessage = vi.spyOn(iframe.contentWindow as Window, "postMessage");
    fireEvent.load(iframe);
    postMessage.mockClear();

    rerender(
      <FreeformCanvas
        code="export default function Canvas() { return null }"
        onDataRequest={vi.fn()}
        clearTextSelectionKey={1}
      />,
    );

    expect(postMessage).toHaveBeenCalledWith(
      { channel: "posthog-canvas", type: "clear-text-selection" },
      "*",
    );
  });

  it("opens a comment selected inside the canvas", () => {
    const onCommentActivate = vi.fn();
    render(
      <FreeformCanvas
        code="export default function Canvas() { return null }"
        onDataRequest={vi.fn()}
        onCommentActivate={onCommentActivate}
      />,
    );
    const iframe = screen.getByTitle("Canvas") as HTMLIFrameElement;

    window.dispatchEvent(
      new MessageEvent("message", {
        source: iframe.contentWindow,
        data: {
          channel: "posthog-canvas",
          type: "comment-activate",
          id: "comment-1",
        },
      }),
    );

    expect(onCommentActivate).toHaveBeenCalledWith("comment-1");
  });

  describe("open-external", () => {
    let userActivationIsActive = true;

    beforeEach(() => {
      vi.useFakeTimers();
      userActivationIsActive = true;
      Object.defineProperty(navigator, "userActivation", {
        configurable: true,
        get: () => ({
          hasBeenActive: true,
          isActive: userActivationIsActive,
        }),
      });
    });

    afterEach(() => {
      vi.useRealTimers();
      vi.mocked(openExternalUrl).mockClear();
      Reflect.deleteProperty(navigator, "userActivation");
    });

    it("opens PostHog https URLs during a user activation", () => {
      const iframe = renderCanvas();

      postFromCanvas(iframe, "https://posthog.com/docs");

      expect(openExternalUrl).toHaveBeenCalledWith("https://posthog.com/docs");
    });

    it("drops opens without a current user activation", () => {
      const iframe = renderCanvas();
      userActivationIsActive = false;
      iframe.focus();

      postFromCanvas(iframe, "https://posthog.com/docs");

      expect(openExternalUrl).not.toHaveBeenCalled();
    });

    it("drops non-PostHog URLs", () => {
      const iframe = renderCanvas();

      postFromCanvas(iframe, "https://example.com");
      postFromCanvas(iframe, "javascript:alert(1)");
      postFromCanvas(iframe, "mailto:hi@posthog.com");

      expect(openExternalUrl).not.toHaveBeenCalled();
    });

    it("throttles rapid opens so canvas code cannot spam the launcher", () => {
      const iframe = renderCanvas();

      postFromCanvas(iframe, "https://posthog.com/a");
      postFromCanvas(iframe, "https://posthog.com/b");
      expect(openExternalUrl).toHaveBeenCalledTimes(1);

      vi.advanceTimersByTime(1_001);
      postFromCanvas(iframe, "https://posthog.com/c");
      expect(openExternalUrl).toHaveBeenCalledTimes(2);
      expect(openExternalUrl).toHaveBeenLastCalledWith("https://posthog.com/c");
    });
  });
});
