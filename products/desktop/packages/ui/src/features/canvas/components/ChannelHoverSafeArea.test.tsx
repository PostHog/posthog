import { fireEvent, render, waitFor } from "@testing-library/react";
import { type ReactElement, useRef } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ChannelHoverSafeArea } from "./ChannelHoverSafeArea";

function rect({
  left,
  top,
  width,
  height,
}: {
  left: number;
  top: number;
  width: number;
  height: number;
}): DOMRect {
  return {
    left,
    top,
    width,
    height,
    right: left + width,
    bottom: top + height,
    x: left,
    y: top,
    toJSON: () => ({}),
  };
}

function Harness(): ReactElement {
  const anchorRef = useRef<HTMLDivElement | null>(null);
  const floatingRef = useRef<HTMLDivElement | null>(null);

  return (
    <>
      <div ref={anchorRef} data-testid="anchor" />
      <ChannelHoverSafeArea anchorRef={anchorRef} floatingRef={floatingRef} />
      <div ref={floatingRef} data-testid="floating" data-side="right" />
    </>
  );
}

describe("ChannelHoverSafeArea", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("starts the safe triangle at the trigger edge", async () => {
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(
      function getBoundingClientRect(): DOMRect {
        if (this.dataset.testid === "anchor") {
          return rect({ left: 0, top: 0, width: 100, height: 40 });
        }
        if (this.dataset.testid === "floating") {
          return rect({ left: 120, top: 0, width: 200, height: 160 });
        }
        return rect({ left: 0, top: 0, width: 0, height: 0 });
      },
    );

    const { getByTestId } = render(<Harness />);
    const anchor = getByTestId("anchor");
    const safeArea = document.querySelector(
      '[data-slot="channel-hover-safe-area"]',
    );
    expect(safeArea).toBeInstanceOf(HTMLElement);

    fireEvent.pointerMove(anchor, { clientX: 50, clientY: 20 });

    await waitFor(() => {
      expect((safeArea as HTMLElement).style.clipPath).toBe(
        "polygon(100px 20px, 120px 0px, 120px 160px)",
      );
    });
  });
});
