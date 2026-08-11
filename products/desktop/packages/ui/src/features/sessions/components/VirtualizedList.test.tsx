import { fireEvent, render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { VirtualizedList } from "./VirtualizedList";

const mocks = vi.hoisted(() => {
  let totalSize = 80;
  const values = {
    getTotalSize: () => totalSize,
    setTotalSize: (value: number) => {
      totalSize = value;
    },
    isAtEnd: vi.fn(() => true),
    measureElement: vi.fn(),
    resizeItem: vi.fn(),
    scrollToEnd: vi.fn(),
    scrollToIndex: vi.fn(),
  };
  return {
    ...values,
    virtualizer: {
      getTotalSize: values.getTotalSize,
      getVirtualItems: () => [{ index: 0, key: "turn-1", start: 0 }],
      isAtEnd: values.isAtEnd,
      measureElement: values.measureElement,
      resizeItem: values.resizeItem,
      scrollToEnd: values.scrollToEnd,
      scrollToIndex: values.scrollToIndex,
    },
  };
});

vi.mock("@tanstack/react-virtual", () => ({
  useVirtualizer: () => mocks.virtualizer,
}));

function renderList() {
  return render(
    <VirtualizedList
      items={[{ id: "turn-1", height: 640 }]}
      getItemKey={(item) => item.id}
      renderItem={(item) => <div data-height={item.height}>turn</div>}
    />,
  );
}

describe("VirtualizedList", () => {
  beforeEach(() => {
    mocks.setTotalSize(80);
    vi.clearAllMocks();
    vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockImplementation(
      function (this: HTMLElement) {
        const value =
          this.querySelector<HTMLElement>("[data-height]")?.dataset.height;
        return value ? Number(value) : 0;
      },
    );
  });

  it("records a variable-height turn when it mounts", () => {
    renderList();

    expect(mocks.resizeItem).toHaveBeenCalledWith(0, 640);
  });

  it("keeps following after a horizontal touch gesture", () => {
    const view = renderList();
    const viewport = view.container.firstElementChild?.firstElementChild;
    expect(viewport).toBeInstanceOf(HTMLElement);
    mocks.scrollToEnd.mockClear();

    fireEvent.touchStart(viewport as Element, {
      touches: [{ clientX: 10, clientY: 10 }],
    });
    fireEvent.touchMove(viewport as Element, {
      touches: [{ clientX: 40, clientY: 12 }],
    });
    mocks.setTotalSize(640);
    view.rerender(
      <VirtualizedList
        items={[{ id: "turn-1", height: 640 }]}
        getItemKey={(item) => item.id}
        renderItem={(item) => <div data-height={item.height}>turn</div>}
      />,
    );

    expect(mocks.scrollToEnd).toHaveBeenCalledOnce();
  });

  it("stops following before a touch gesture scrolls toward older turns", () => {
    const view = renderList();
    const viewport = view.container.firstElementChild?.firstElementChild;
    expect(viewport).toBeInstanceOf(HTMLElement);
    mocks.scrollToEnd.mockClear();

    fireEvent.touchStart(viewport as Element, {
      touches: [{ clientX: 10, clientY: 10 }],
    });
    fireEvent.touchMove(viewport as Element, {
      touches: [{ clientX: 12, clientY: 40 }],
    });
    mocks.setTotalSize(640);
    view.rerender(
      <VirtualizedList
        items={[{ id: "turn-1", height: 640 }]}
        getItemKey={(item) => item.id}
        renderItem={(item) => <div data-height={item.height}>turn</div>}
      />,
    );

    expect(mocks.scrollToEnd).not.toHaveBeenCalled();
  });
});
