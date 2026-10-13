import type { CanvasToHostMessage } from "@posthog/core/canvas/freeformSchemas";
import { renderHook } from "@testing-library/react";
import { useHotkeys } from "react-hotkeys-hook";
import { afterEach, describe, expect, it, type Mock, vi } from "vitest";
import { createCanvasHostMessageRouter } from "./canvasHostMessageRouter";

interface Harness {
  onCommandMenu: Mock;
  onReload: Mock;
  route: (message: CanvasToHostMessage) => Promise<void>;
}

describe("canvas keydown replay", () => {
  afterEach(() => {
    document.body.replaceChildren();
  });

  function focusCanvasFrame(): void {
    const frame = document.createElement("iframe");
    document.body.append(frame);
    frame.focus();
  }

  function setup(): Harness {
    const onCommandMenu = vi.fn();
    const onReload = vi.fn();
    renderHook(() => {
      useHotkeys("mod+k", onCommandMenu, { enableOnFormTags: true });
      useHotkeys("mod+shift+r", onReload, { enableOnFormTags: true });
    });
    const route = createCanvasHostMessageRouter({
      post: vi.fn(),
      callbacks: () => ({ onDataRequest: vi.fn() }),
      hasUserActivation: () => false,
      openExternal: vi.fn(),
    });
    return { onCommandMenu, onReload, route };
  }

  const commandMenuKeydown: CanvasToHostMessage = {
    channel: "posthog-canvas",
    type: "keydown",
    key: "k",
    code: "KeyK",
    metaKey: false,
    ctrlKey: true,
    shiftKey: false,
    altKey: false,
  };

  it("fires the app hotkey for a combo pressed inside the canvas", async () => {
    const { onCommandMenu, route } = setup();
    focusCanvasFrame();

    await route(commandMenuKeydown);

    expect(onCommandMenu).toHaveBeenCalledTimes(1);
  });

  it("leaves no key held, so a later bare modifier press does not fire it again", async () => {
    const { onCommandMenu, route } = setup();
    focusCanvasFrame();
    await route(commandMenuKeydown);

    document.dispatchEvent(
      new KeyboardEvent("keydown", {
        key: "Control",
        code: "ControlLeft",
        ctrlKey: true,
      }),
    );

    expect(onCommandMenu).toHaveBeenCalledTimes(1);
  });

  it("ignores a shortcut outside the replayable set, so canvas code cannot reload the window", async () => {
    const { onReload, route } = setup();
    focusCanvasFrame();

    await route({
      ...commandMenuKeydown,
      key: "r",
      code: "KeyR",
      shiftKey: true,
    });

    expect(onReload).not.toHaveBeenCalled();
  });

  it("ignores a keydown while the focus sits outside a canvas frame", async () => {
    const { onCommandMenu, route } = setup();

    await route(commandMenuKeydown);

    expect(onCommandMenu).not.toHaveBeenCalled();
  });
});
