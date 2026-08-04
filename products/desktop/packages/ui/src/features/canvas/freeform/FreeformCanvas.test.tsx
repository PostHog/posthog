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
