import type { PiRemoteRpcClient } from "@posthog/agent/pi/remote-rpc-client";
import type { PiExtensionEvent } from "@posthog/agent/pi/types";
import { describe, expect, it, vi } from "vitest";
import { PiExtensionController } from "./piExtensionController";
import type { PiSession, PiSessionProvider } from "./piSessionController";

interface ExtensionSubscriptionHandlers {
  event: (event: PiExtensionEvent) => void;
  error: (error: unknown) => void;
  complete: () => void;
}

function createSession(handlers: ExtensionSubscriptionHandlers[]): PiSession {
  return {
    client: {} as PiRemoteRpcClient,
    health: vi.fn(async () => ({ state: "idle" as const })),
    getConversation: vi.fn(async () => []),
    getQueue: vi.fn(async () => ({ steering: [], followUp: [] })),
    clearQueue: vi.fn(async () => ({ steering: [], followUp: [] })),
    onConversationEvent: vi.fn(() => () => {}),
    onExtensionEvent: vi.fn((event, error, complete = () => {}) => {
      handlers.push({ event, error, complete });
      return vi.fn();
    }),
    respondToExtensionUI: vi.fn(async () => {}),
  };
}

function createController(session: PiSession): PiExtensionController {
  const provider: PiSessionProvider = {
    get: vi.fn(async () => session),
  };
  return new PiExtensionController(provider);
}

describe("PiExtensionController", () => {
  it("applies official extension events and responds to dialogs", async () => {
    const handlers: ExtensionSubscriptionHandlers[] = [];
    const session = createSession(handlers);
    const controller = createController(session);
    await controller.connect("task-1");

    handlers[0].event({
      type: "extension_ui_request",
      id: "confirm-1",
      method: "confirm",
      title: "Continue?",
      message: "Proceed?",
    });
    handlers[0].event({
      type: "extension_ui_request",
      id: "status-1",
      method: "setStatus",
      statusKey: "build",
      statusText: "Running",
    });
    handlers[0].event({
      type: "extension_ui_request",
      id: "widget-1",
      method: "setWidget",
      widgetKey: "summary",
      widgetLines: ["Ready"],
    });
    handlers[0].event({
      type: "extension_ui_request",
      id: "editor-1",
      method: "set_editor_text",
      text: "draft",
    });

    expect(controller.store.getState().tasks["task-1"]).toMatchObject({
      dialogs: [expect.objectContaining({ id: "confirm-1" })],
      statuses: { build: "Running" },
      widgets: {
        summary: { lines: ["Ready"], placement: "aboveEditor" },
      },
      editorText: { id: "editor-1", text: "draft" },
    });

    const response = {
      type: "extension_ui_response" as const,
      id: "confirm-1",
      confirmed: true,
    };
    await controller.respondToExtensionUI("task-1", response);

    expect(session.respondToExtensionUI).toHaveBeenCalledWith(response);
    expect(controller.store.getState().tasks["task-1"].dialogs).toEqual([]);
  });

  it("expires timed dialogs without a custom lifecycle event", async () => {
    vi.useFakeTimers();
    try {
      const handlers: ExtensionSubscriptionHandlers[] = [];
      const session = createSession(handlers);
      const controller = createController(session);
      await controller.connect("task-1");

      handlers[0].event({
        type: "extension_ui_request",
        id: "input-1",
        method: "input",
        title: "Name",
        timeout: 50,
      });
      await vi.advanceTimersByTimeAsync(50);

      expect(controller.store.getState().tasks["task-1"].dialogs).toEqual([]);
      expect(session.respondToExtensionUI).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });

  it("cancels an untimed dialog when its view disconnects", async () => {
    const handlers: ExtensionSubscriptionHandlers[] = [];
    const session = createSession(handlers);
    const controller = createController(session);
    await controller.connect("task-1");

    handlers[0].event({
      type: "extension_ui_request",
      id: "input-1",
      method: "input",
      title: "Name",
    });
    controller.disconnect("task-1");

    await vi.waitFor(() =>
      expect(session.respondToExtensionUI).toHaveBeenCalledWith({
        type: "extension_ui_response",
        id: "input-1",
        cancelled: true,
      }),
    );
    expect(controller.store.getState().tasks["task-1"]).toBeUndefined();
  });

  it("does not recreate cleared state when an in-flight response settles", async () => {
    let resolveResponse: () => void = () => {};
    const handlers: ExtensionSubscriptionHandlers[] = [];
    const session = createSession(handlers);
    session.respondToExtensionUI = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          resolveResponse = resolve;
        }),
    );
    const controller = createController(session);
    await controller.connect("task-1");
    handlers[0].event({
      type: "extension_ui_request",
      id: "confirm-1",
      method: "confirm",
      title: "Continue?",
      message: "Proceed?",
    });

    const delivery = controller.respondToExtensionUI("task-1", {
      type: "extension_ui_response",
      id: "confirm-1",
      confirmed: true,
    });
    await vi.waitFor(() =>
      expect(session.respondToExtensionUI).toHaveBeenCalledOnce(),
    );
    controller.disconnect("task-1");
    resolveResponse();
    await delivery;

    expect(controller.store.getState().tasks["task-1"]).toBeUndefined();
  });

  it("clears ephemeral state on reconnect and ignores stale callbacks", async () => {
    vi.useFakeTimers();
    try {
      const handlers: ExtensionSubscriptionHandlers[] = [];
      const session = createSession(handlers);
      const controller = createController(session);
      await controller.connect("task-1");

      handlers[0].event({
        type: "extension_ui_request",
        id: "old-dialog",
        method: "input",
        title: "Name",
      });
      handlers[0].error(new Error("stream closed"));

      expect(controller.store.getState().tasks["task-1"]).toMatchObject({
        dialogs: [],
        statuses: {},
        widgets: {},
        notifications: [
          expect.objectContaining({
            message: expect.stringContaining("stream closed"),
          }),
        ],
      });
      await vi.waitFor(() =>
        expect(session.respondToExtensionUI).toHaveBeenCalledWith({
          type: "extension_ui_response",
          id: "old-dialog",
          cancelled: true,
        }),
      );

      await vi.advanceTimersByTimeAsync(100);
      await vi.waitFor(() => expect(handlers).toHaveLength(2));

      handlers[0].event({
        type: "extension_ui_request",
        id: "stale-dialog",
        method: "input",
        title: "Stale",
      });
      handlers[1].event({
        type: "extension_ui_request",
        id: "new-dialog",
        method: "input",
        title: "Current",
      });

      expect(
        controller.store.getState().tasks["task-1"].dialogs.map(({ id }) => id),
      ).toEqual(["new-dialog"]);
    } finally {
      vi.useRealTimers();
    }
  });
});
