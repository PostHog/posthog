import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FreeformCanvas } from "./FreeformCanvas";

vi.mock("@posthog/ui/shell/openExternal", () => ({
  openExternalUrl: vi.fn(),
}));

const renderCanvas = () => {
  render(
    <FreeformCanvas
      code="export default function Canvas() { return null }"
      mode="edit"
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

  describe("open-external", () => {
    beforeEach(() => {
      vi.useFakeTimers();
    });

    afterEach(() => {
      vi.useRealTimers();
      vi.mocked(openExternalUrl).mockClear();
    });

    it("opens PostHog https URLs once the user has focused the canvas", () => {
      const iframe = renderCanvas();
      iframe.focus();

      postFromCanvas(iframe, "https://posthog.com/docs");

      expect(openExternalUrl).toHaveBeenCalledWith("https://posthog.com/docs");
    });

    it("drops opens when the user has not interacted with the canvas", () => {
      const iframe = renderCanvas();

      postFromCanvas(iframe, "https://posthog.com/docs");

      expect(openExternalUrl).not.toHaveBeenCalled();
    });

    it("drops non-PostHog URLs", () => {
      const iframe = renderCanvas();
      iframe.focus();

      postFromCanvas(iframe, "https://example.com");
      postFromCanvas(iframe, "javascript:alert(1)");
      postFromCanvas(iframe, "mailto:hi@posthog.com");

      expect(openExternalUrl).not.toHaveBeenCalled();
    });

    it("throttles rapid opens so canvas code cannot spam the launcher", () => {
      const iframe = renderCanvas();
      iframe.focus();

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
