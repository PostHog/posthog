import { fireEvent, render, waitFor } from "@testing-library/react";
import { type ReactElement, useRef } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ChannelPreviewPointerGrace } from "./ChannelPreviewPointerGrace";

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
  const triggerRef = useRef<HTMLDivElement | null>(null);
  const floatingRef = useRef<HTMLDivElement | null>(null);

  return (
    <>
      <div ref={triggerRef} data-testid="source" data-channel-preview-trigger />
      <div data-testid="sibling" data-channel-preview-trigger />
      <ChannelPreviewPointerGrace
        triggerRef={triggerRef}
        floatingRef={floatingRef}
      />
      <div
        ref={floatingRef}
        data-testid="floating"
        data-side="right"
        data-align="start"
      />
    </>
  );
}

describe("ChannelPreviewPointerGrace", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("blocks sibling triggers only while the pointer remains in the safe polygon", async () => {
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(
      function getBoundingClientRect(this: HTMLElement): DOMRect {
        if (this.dataset.testid === "source") {
          return rect({ left: 0, top: 0, width: 100, height: 40 });
        }
        if (this.dataset.testid === "floating") {
          return rect({ left: 120, top: 0, width: 200, height: 160 });
        }
        return rect({ left: 0, top: 0, width: 0, height: 0 });
      },
    );

    const { getByTestId } = render(<Harness />);
    const source = getByTestId("source");
    const sibling = getByTestId("sibling");
    const floating = getByTestId("floating");

    fireEvent.mouseEnter(source);
    fireEvent.mouseLeave(source, {
      clientX: 100,
      clientY: 20,
      relatedTarget: document.body,
    });
    fireEvent.mouseMove(document, { clientX: 110, clientY: 80 });

    expect(source.style.pointerEvents).toBe("auto");
    expect(sibling.style.pointerEvents).toBe("none");

    fireEvent.mouseEnter(floating);
    expect(source.style.pointerEvents).toBe("");
    expect(sibling.style.pointerEvents).toBe("");

    fireEvent.mouseEnter(source);
    fireEvent.mouseLeave(source, {
      clientX: 100,
      clientY: 20,
      relatedTarget: document.body,
    });
    fireEvent.mouseMove(document, { clientX: 0, clientY: 200 });

    await waitFor(() => {
      expect(source.style.pointerEvents).toBe("");
      expect(sibling.style.pointerEvents).toBe("");
    });
  });
});
