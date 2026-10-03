import { fireEvent, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { usePinnedAutoScroll } from "./usePinnedAutoScroll";

let resizeCallback: ResizeObserverCallback;

class ResizeObserverMock {
  constructor(callback: ResizeObserverCallback) {
    resizeCallback = callback;
  }

  observe = vi.fn();
  disconnect = vi.fn();
}

function TestScroller() {
  const { containerRef, contentRef, onScroll } = usePinnedAutoScroll();

  return (
    <div ref={containerRef} data-testid="scroller" onScroll={onScroll}>
      <div ref={contentRef}>Timeline</div>
    </div>
  );
}

describe("usePinnedAutoScroll", () => {
  beforeEach(() => {
    vi.stubGlobal("ResizeObserver", ResizeObserverMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("follows growth only while the viewer is at the bottom", () => {
    const { getByTestId } = render(<TestScroller />);
    const scroller = getByTestId("scroller");
    let scrollHeight = 200;

    Object.defineProperties(scroller, {
      clientHeight: { configurable: true, value: 100 },
      scrollHeight: { configurable: true, get: () => scrollHeight },
    });

    scroller.scrollTop = 100;
    fireEvent.scroll(scroller);
    scrollHeight = 250;
    resizeCallback([], {} as ResizeObserver);
    expect(scroller.scrollTop).toBe(250);

    scroller.scrollTop = 80;
    fireEvent.scroll(scroller);
    scrollHeight = 300;
    resizeCallback([], {} as ResizeObserver);
    expect(scroller.scrollTop).toBe(80);

    scroller.scrollTop = 200;
    fireEvent.scroll(scroller);
    scrollHeight = 350;
    resizeCallback([], {} as ResizeObserver);
    expect(scroller.scrollTop).toBe(350);
  });
});
