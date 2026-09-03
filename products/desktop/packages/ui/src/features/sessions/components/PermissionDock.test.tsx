import {
  act,
  fireEvent,
  render,
  renderHook,
  screen,
} from "@testing-library/react";
import { useEffect } from "react";
import { beforeEach, describe, expect, it } from "vitest";
import { useSessionViewActions } from "../sessionViewStore";
import { PermissionDock } from "./PermissionDock";

/** jsdom measures everything as 0, so the sizes under test are stubbed on. */
function stubHeights(separator: HTMLElement, dock: number, container: number) {
  const dockEl = separator.parentElement?.parentElement;
  const containerEl = dockEl?.parentElement;
  if (!dockEl || !containerEl) throw new Error("dock not found");
  dockEl.getBoundingClientRect = () => ({ height: dock }) as DOMRect;
  containerEl.getBoundingClientRect = () => ({ height: container }) as DOMRect;
  return dockEl;
}

describe("PermissionDock", () => {
  beforeEach(() => {
    const { result } = renderHook(() => useSessionViewActions());
    act(() => result.current.setPermissionDockHeight(null));
  });

  it.each([
    { name: "grows by one step", key: "ArrowUp", dock: 300, expected: "340px" },
    {
      name: "shrinks by one step",
      key: "ArrowDown",
      dock: 300,
      expected: "260px",
    },
    {
      name: "stops short of the thread's reserved room",
      key: "ArrowUp",
      dock: 470,
      expected: "480px",
    },
    {
      name: "stops at the shortest useful dock",
      key: "ArrowDown",
      dock: 100,
      expected: "96px",
    },
  ])("resizing with the keyboard $name", ({ key, dock, expected }) => {
    render(
      <div>
        <PermissionDock compact={false}>
          <div>Question card</div>
        </PermissionDock>
      </div>,
    );

    const separator = screen.getByRole("separator");
    const dockEl = stubHeights(separator, dock, 600);

    fireEvent.keyDown(separator, { key });

    // The reserve rides along in CSS, so the height the drag settled on is the
    // first term of the applied `min()`.
    expect(dockEl.style.maxHeight).toBe(`min(${expected}, calc(100% - 120px))`);
  });

  it("reaching the handle after a window resize reports the current range", () => {
    render(
      <div>
        <PermissionDock compact={false}>
          <div>Question card</div>
        </PermissionDock>
      </div>,
    );

    const separator = screen.getByRole("separator");
    stubHeights(separator, 300, 600);
    fireEvent.focus(separator);
    expect(separator.getAttribute("aria-valuenow")).toBe("300");
    expect(separator.getAttribute("aria-valuemax")).toBe("480");

    // The window shrinks: CSS re-caps the dock with no React render behind it.
    stubHeights(separator, 200, 400);
    fireEvent.focus(separator);

    expect(separator.getAttribute("aria-valuenow")).toBe("200");
    expect(separator.getAttribute("aria-valuemax")).toBe("280");
  });

  it("releasing the button outside the window ends the drag", () => {
    render(
      <div>
        <PermissionDock compact={false}>
          <div>Question card</div>
        </PermissionDock>
      </div>,
    );

    const separator = screen.getByRole("separator");
    const dockEl = stubHeights(separator, 300, 600);
    fireEvent.mouseDown(separator, { clientY: 400 });
    fireEvent.mouseMove(document, { clientY: 360, buttons: 1 });
    const draggedTo = dockEl.style.maxHeight;

    // No mouseup ever arrives; the pointer just comes back with nothing held.
    fireEvent.mouseMove(document, { clientY: 200, buttons: 0 });
    fireEvent.mouseMove(document, { clientY: 100, buttons: 1 });

    expect(document.body.style.cursor).toBe("");
    expect(dockEl.style.maxHeight).toBe(draggedTo);
  });

  it("answering mid-drag leaves the app without a stuck cursor", () => {
    const { unmount } = render(
      <div>
        <PermissionDock compact={false}>
          <div>Question card</div>
        </PermissionDock>
      </div>,
    );

    const separator = screen.getByRole("separator");
    stubHeights(separator, 300, 600);
    fireEvent.mouseDown(separator, { clientY: 400 });
    expect(document.body.style.cursor).toBe("row-resize");

    unmount();

    expect(document.body.style.cursor).toBe("");
    expect(document.body.style.userSelect).toBe("");
  });

  it("hiding and showing again keeps the card's own state", () => {
    let mounts = 0;
    function Card() {
      useEffect(() => {
        mounts += 1;
      }, []);
      return <div>Question card</div>;
    }

    render(
      <PermissionDock compact={false}>
        <Card />
      </PermissionDock>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Hide" }));
    expect(screen.getByText("Waiting for your response")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Show" }));
    expect(screen.getByText("Question card")).toBeTruthy();
    expect(mounts).toBe(1);
  });
});
