import type { PiRemoteRpcClient } from "@posthog/agent/pi/remote-rpc-client";
import type { AuthService } from "@posthog/core/auth/auth";
import type { TaskService } from "@posthog/core/task-detail/taskService";
import type { AgentConversationEvent } from "@posthog/shared";
import { describe, expect, it, vi } from "vitest";
import {
  PiOperationError,
  type PiSession,
  PiSessionController,
  type PiSessionProvider,
} from "./piSessionController";

function createController(
  session = createSession(),
  taskService = {
    openTask: vi.fn(async () => ({ success: true })),
  } as unknown as TaskService,
  authService?: AuthService,
): PiSessionController {
  const provider: PiSessionProvider = {
    get: vi.fn(async () => session),
  };
  return new PiSessionController(provider, taskService, authService);
}

function createSession(): PiSession {
  const client = {
    getState: vi.fn(async () => ({
      thinkingLevel: "off" as const,
      isStreaming: false,
      isCompacting: false,
      steeringMode: "all" as const,
      followUpMode: "all" as const,
      sessionId: "session-1",
      autoCompactionEnabled: true,
      messageCount: 0,
      pendingMessageCount: 0,
    })),
    getSessionStats: vi.fn(async () => ({
      sessionFile: undefined,
      sessionId: "session-1",
      userMessages: 0,
      assistantMessages: 0,
      toolCalls: 0,
      toolResults: 0,
      totalMessages: 0,
      tokens: {
        input: 0,
        output: 0,
        cacheRead: 0,
        cacheWrite: 0,
        total: 0,
      },
      cost: 0,
      contextUsage: undefined,
    })),
    getAvailableModels: vi.fn(async () => []),
    getAvailableThinkingLevels: vi.fn(async () => ["off" as const]),
    getCommands: vi.fn(async () => []),
    prompt: vi.fn(async () => {}),
    steer: vi.fn(async () => {}),
    followUp: vi.fn(async () => {}),
    compact: vi.fn(async () => undefined),
    setModel: vi.fn(async (provider, id) => ({ provider, id })),
    setThinkingLevel: vi.fn(async () => {}),
    bash: vi.fn(async () => undefined),
    abort: vi.fn(async () => {}),
    abortBash: vi.fn(async () => {}),
  } as unknown as PiRemoteRpcClient;

  return {
    client,
    health: vi.fn(async () => ({ state: "idle" as const })),
    getConversation: vi.fn(async () => []),
    getQueue: vi.fn(async () => ({ steering: [], followUp: [] })),
    clearQueue: vi.fn(async () => ({ steering: [], followUp: [] })),
    onConversationEvent: vi.fn(() => () => {}),
  };
}

describe("PiSessionController", () => {
  it.each([
    {
      text: "hello",
      streaming: false,
      mode: "steer" as const,
      action: "prompt",
    },
    { text: "hello", streaming: true, mode: "steer" as const, action: "steer" },
    {
      text: "hello",
      streaming: true,
      mode: "queue" as const,
      action: "followUp",
    },
    {
      text: "/compact keep details",
      streaming: false,
      mode: "steer" as const,
      action: "compact",
    },
  ])("classifies $action submissions", ({ text, streaming, mode, action }) => {
    const controller = createController();

    expect(controller.getSubmitAction(text, streaming, mode)).toBe(action);
  });

  it.each([
    {
      text: "hello",
      streaming: false,
      mode: "steer" as const,
      method: "prompt" as const,
      expectedArgs: ["hello"],
    },
    {
      text: "hello",
      streaming: true,
      mode: "steer" as const,
      method: "steer" as const,
      expectedArgs: ["hello"],
    },
    {
      text: "hello",
      streaming: true,
      mode: "queue" as const,
      method: "followUp" as const,
      expectedArgs: ["hello"],
    },
    {
      text: "/compact keep details",
      streaming: false,
      mode: "steer" as const,
      method: "compact" as const,
      expectedArgs: ["keep details"],
    },
  ])("routes submissions through $method", async (input) => {
    const client = createSession();
    const controller = createController(client);

    await controller.submit("task-1", input.text, input.streaming, input.mode);

    expect(client.client[input.method]).toHaveBeenCalledWith(
      ...input.expectedArgs,
    );
    expect(client.getConversation).not.toHaveBeenCalled();
  });

  it("loads repository trust and reconnects after changing it", async () => {
    let trusted = false;
    const session = createSession();
    session.getProjectTrust = vi.fn(async () => ({
      trusted,
      hasProjectResources: true,
    }));
    session.setProjectTrusted = vi.fn(async (nextTrusted) => {
      trusted = nextTrusted;
    });
    const controller = createController(session);

    await controller.connect("task-1");
    expect(controller.store.getState().sessions["task-1"].projectTrust).toEqual(
      {
        trusted: false,
        hasProjectResources: true,
      },
    );
    controller.store.setState((state) => ({
      sessions: {
        ...state.sessions,
        "task-1": {
          ...state.sessions["task-1"],
          queue: { steering: ["queued"], followUp: [] },
        },
      },
    }));

    await controller.setProjectTrusted("task-1", true);

    expect(session.setProjectTrusted).toHaveBeenCalledWith(true);
    expect(session.client.prompt).toHaveBeenCalledWith("queued");
    expect(controller.store.getState().sessions["task-1"].projectTrust).toEqual(
      {
        trusted: true,
        hasProjectResources: true,
      },
    );
  });

  it("shares an in-flight repository trust change and rejects an opposite toggle", async () => {
    let finishTransition: (() => void) | undefined;
    const session = createSession();
    session.setProjectTrusted = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          finishTransition = resolve;
        }),
    );
    const controller = createController(session);
    await controller.connect("task-1");

    const first = controller.setProjectTrusted("task-1", true);
    const duplicate = controller.setProjectTrusted("task-1", true);
    await expect(controller.setProjectTrusted("task-1", false)).rejects.toThrow(
      "already in progress",
    );
    expect(session.setProjectTrusted).toHaveBeenCalledOnce();

    finishTransition?.();
    await expect(Promise.all([first, duplicate])).resolves.toEqual([
      undefined,
      undefined,
    ]);
  });

  it.each([
    { streaming: true, bashRunning: false },
    { streaming: false, bashRunning: true },
  ])(
    "rejects repository trust changes while Pi is busy",
    async ({ streaming, bashRunning }) => {
      const session = createSession();
      session.setProjectTrusted = vi.fn(async () => {});
      const controller = createController(session);
      await controller.connect("task-1");
      const current = controller.store.getState().sessions["task-1"];
      const status = current.status;
      if (!status) {
        throw new Error("Expected connected Pi status");
      }
      controller.store.setState((state) => ({
        sessions: {
          ...state.sessions,
          "task-1": {
            ...state.sessions["task-1"],
            status: {
              ...status,
              isStreaming: streaming,
            },
            isBashRunning: bashRunning,
          },
        },
      }));

      await expect(
        controller.setProjectTrusted("task-1", true),
      ).rejects.toBeInstanceOf(PiOperationError);
      expect(session.setProjectTrusted).not.toHaveBeenCalled();
    },
  );

  it("queues extension dialogs and applies replacement, removal, and error events", async () => {
    let onExtensionEvent: (
      event: import("@posthog/agent/pi/types").PiExtensionEvent,
    ) => void = () => {};
    const session = createSession();
    session.respondToExtensionUI = vi.fn(async () => {});
    session.onExtensionEvent = vi.fn((handler) => {
      onExtensionEvent = handler;
      return () => {};
    });
    const controller = createController(session);

    await controller.connect("task-1");
    onExtensionEvent({
      type: "extension_ui_request",
      id: "select-1",
      method: "select",
      title: "Pick one",
      options: ["A", "B"],
    });
    onExtensionEvent({
      type: "extension_ui_request",
      id: "confirm-1",
      method: "confirm",
      title: "Continue?",
      message: "Are you sure?",
    });

    expect(
      controller.store
        .getState()
        .sessions["task-1"].extensionDialogs.map((dialog) => dialog.id),
    ).toEqual(["select-1", "confirm-1"]);
    await controller.respondToExtensionUI("task-1", {
      type: "extension_ui_response",
      id: "select-1",
      value: "B",
    });
    await controller.cancelExtensionUI("task-1", "select-1");
    expect(session.respondToExtensionUI).toHaveBeenCalledTimes(1);
    expect(
      controller.store.getState().sessions["task-1"].extensionDialogs[0]?.id,
    ).toBe("confirm-1");

    onExtensionEvent({
      type: "extension_ui_request",
      id: "status-1",
      method: "setStatus",
      statusKey: "build",
      statusText: "Running",
    });
    onExtensionEvent({
      type: "extension_ui_request",
      id: "status-2",
      method: "setStatus",
      statusKey: "build",
      statusText: "Done",
    });
    onExtensionEvent({
      type: "extension_ui_request",
      id: "widget-1",
      method: "setWidget",
      widgetKey: "summary",
      widgetLines: ["one", "two"],
      widgetPlacement: "belowEditor",
    });
    expect(controller.store.getState().sessions["task-1"]).toMatchObject({
      extensionStatuses: { build: "Done" },
      extensionWidgets: {
        summary: { lines: ["one", "two"], placement: "belowEditor" },
      },
    });

    onExtensionEvent({
      type: "extension_ui_request",
      id: "status-3",
      method: "setStatus",
      statusKey: "build",
      statusText: undefined,
    });
    onExtensionEvent({
      type: "extension_ui_request",
      id: "widget-2",
      method: "setWidget",
      widgetKey: "summary",
      widgetLines: undefined,
    });
    onExtensionEvent({
      type: "extension_ui_request",
      id: "notify-1",
      method: "notify",
      message: "Extension finished",
      notifyType: "warning",
    });
    onExtensionEvent({
      type: "extension_ui_request",
      id: "title-1",
      method: "setTitle",
      title: "Extension task",
    });
    onExtensionEvent({
      type: "extension_ui_request",
      id: "editor-text-1",
      method: "set_editor_text",
      text: "replacement draft",
    });
    onExtensionEvent({
      type: "extension_error",
      extensionPath: "/extensions/example.ts",
      event: "tool_call",
      error: "boom",
    });
    expect(controller.store.getState().sessions["task-1"]).toMatchObject({
      extensionStatuses: {},
      extensionWidgets: {},
      extensionTitle: "Extension task",
      extensionEditorText: {
        id: "editor-text-1",
        text: "replacement draft",
      },
      error: undefined,
      extensionNotifications: [
        {
          id: "notify-1",
          notifyType: "warning",
          message: "Extension finished",
        },
        expect.objectContaining({
          notifyType: "error",
          message: expect.stringContaining("boom"),
        }),
      ],
    });
  });

  it("applies unconsumed state from an authoritative extension snapshot", async () => {
    let onExtensionEvent: (
      event: import("@posthog/agent/pi/types").PiExtensionEvent,
    ) => void = () => {};
    const session = createSession();
    session.onExtensionEvent = vi.fn((handler) => {
      onExtensionEvent = handler;
      return () => {};
    });
    const controller = createController(session);
    await controller.connect("task-1");

    onExtensionEvent({
      type: "extension_state_snapshot",
      dialogs: [
        {
          type: "extension_ui_request",
          id: "dialog-1",
          method: "confirm",
          title: "Continue?",
          message: "Proceed?",
        },
      ],
      statuses: [
        {
          type: "extension_ui_request",
          id: "status-1",
          method: "setStatus",
          statusKey: "build",
          statusText: "Running",
        },
      ],
      widgets: [
        {
          type: "extension_ui_request",
          id: "widget-1",
          method: "setWidget",
          widgetKey: "summary",
          widgetLines: ["content"],
        },
      ],
      title: {
        type: "extension_ui_request",
        id: "title-1",
        method: "setTitle",
        title: "Extension title",
      },
      editorText: {
        type: "extension_ui_request",
        id: "editor-1",
        method: "set_editor_text",
        text: "draft",
      },
    });

    expect(controller.store.getState().sessions["task-1"]).toMatchObject({
      extensionDialogs: [expect.objectContaining({ id: "dialog-1" })],
      extensionStatuses: { build: "Running" },
      extensionWidgets: {
        summary: { lines: ["content"], placement: "aboveEditor" },
      },
      extensionTitle: "Extension title",
      extensionEditorText: { id: "editor-1", text: "draft" },
    });
  });

  it("consumes editor text locally and retries acknowledgement without replaying it", async () => {
    vi.useFakeTimers();
    try {
      let onExtensionEvent: (
        event: import("@posthog/agent/pi/types").PiExtensionEvent,
      ) => void = () => {};
      let onExtensionError: (error: unknown) => void = () => {};
      const session = createSession();
      session.acknowledgeExtensionEditorText = vi
        .fn<() => Promise<void>>()
        .mockRejectedValueOnce(new Error("ack lost"))
        .mockResolvedValueOnce();
      session.onExtensionEvent = vi.fn((handler, errorHandler) => {
        onExtensionEvent = handler;
        onExtensionError = errorHandler;
        return () => {};
      });
      const controller = createController(session);
      const connected = controller.connect("task-1");
      await vi.runAllTimersAsync();
      await connected;
      onExtensionEvent({
        type: "extension_ui_request",
        id: "editor-1",
        method: "set_editor_text",
        text: "first draft",
      });

      controller.acknowledgeExtensionEditorText("task-1", "editor-1");
      expect(
        controller.store.getState().sessions["task-1"].extensionEditorText,
      ).toBeUndefined();
      await vi.waitFor(() =>
        expect(session.acknowledgeExtensionEditorText).toHaveBeenCalledOnce(),
      );
      onExtensionError(new Error("subscription closed"));
      await vi.advanceTimersByTimeAsync(100);
      await vi.waitFor(() => {
        expect(session.onExtensionEvent).toHaveBeenCalledTimes(2);
        expect(session.acknowledgeExtensionEditorText).toHaveBeenCalledTimes(2);
      });

      onExtensionEvent({
        type: "extension_state_snapshot",
        dialogs: [],
        statuses: [],
        widgets: [],
        editorText: {
          type: "extension_ui_request",
          id: "editor-1",
          method: "set_editor_text",
          text: "first draft replay",
        },
      });
      expect(
        controller.store.getState().sessions["task-1"].extensionEditorText,
      ).toBeUndefined();
      controller.acknowledgeExtensionEditorText("task-1", "editor-1");
      expect(session.acknowledgeExtensionEditorText).toHaveBeenCalledTimes(2);
      onExtensionEvent({ type: "extension_session_reset" });
    } finally {
      vi.useRealTimers();
    }
  });

  it("removes an expired extension dialog without sending a late response", async () => {
    let onExtensionEvent: (
      event: import("@posthog/agent/pi/types").PiExtensionEvent,
    ) => void = () => {};
    const session = createSession();
    session.respondToExtensionUI = vi.fn(async () => {});
    session.onExtensionEvent = vi.fn((handler) => {
      onExtensionEvent = handler;
      return () => {};
    });
    const controller = createController(session);
    await controller.connect("task-1");

    onExtensionEvent({
      type: "extension_ui_request",
      id: "input-1",
      method: "input",
      title: "Name",
      timeout: 50,
    });
    onExtensionEvent({ type: "extension_dialog_expired", id: "input-1" });

    expect(
      controller.store.getState().sessions["task-1"].extensionDialogs,
    ).toEqual([]);
    expect(session.respondToExtensionUI).not.toHaveBeenCalled();
  });

  it("keeps a dialog available after response failure and retries successfully", async () => {
    let onExtensionEvent: (
      event: import("@posthog/agent/pi/types").PiExtensionEvent,
    ) => void = () => {};
    const session = createSession();
    session.respondToExtensionUI = vi
      .fn<() => Promise<void>>()
      .mockRejectedValueOnce(new Error("wire unavailable"))
      .mockResolvedValueOnce();
    session.onExtensionEvent = vi.fn((handler) => {
      onExtensionEvent = handler;
      return () => {};
    });
    const controller = createController(session);
    await controller.connect("task-1");
    onExtensionEvent({
      type: "extension_ui_request",
      id: "confirm-1",
      method: "confirm",
      title: "Continue?",
      message: "Proceed?",
    });
    const response = {
      type: "extension_ui_response" as const,
      id: "confirm-1",
      confirmed: true,
    };

    await expect(
      controller.respondToExtensionUI("task-1", response),
    ).rejects.toThrow("wire unavailable");
    expect(
      controller.store.getState().sessions["task-1"].extensionDialogs,
    ).toHaveLength(1);
    expect(
      controller.store.getState().sessions["task-1"].extensionNotifications,
    ).toEqual([
      expect.objectContaining({
        notifyType: "error",
        message: expect.stringContaining("wire unavailable"),
      }),
    ]);

    await controller.respondToExtensionUI("task-1", response);

    expect(session.respondToExtensionUI).toHaveBeenCalledTimes(2);
    expect(
      controller.store.getState().sessions["task-1"].extensionDialogs,
    ).toEqual([]);
  });

  it("preserves an in-flight response across subscription error and replay", async () => {
    vi.useFakeTimers();
    try {
      let onExtensionEvent: (
        event: import("@posthog/agent/pi/types").PiExtensionEvent,
      ) => void = () => {};
      let onExtensionError: (error: unknown) => void = () => {};
      let resolveDelivery: () => void = () => {};
      const session = createSession();
      session.respondToExtensionUI = vi.fn(
        () =>
          new Promise<void>((resolve) => {
            resolveDelivery = resolve;
          }),
      );
      session.onExtensionEvent = vi.fn((handler, errorHandler) => {
        onExtensionEvent = handler;
        onExtensionError = errorHandler;
        return () => {};
      });
      const controller = createController(session);
      const connected = controller.connect("task-1");
      await vi.runAllTimersAsync();
      await connected;
      const request = {
        type: "extension_ui_request" as const,
        id: "confirm-1",
        method: "confirm" as const,
        title: "Continue?",
        message: "Proceed?",
      };
      const response = {
        type: "extension_ui_response" as const,
        id: "confirm-1",
        confirmed: true,
      };
      onExtensionEvent(request);
      const delivery = controller.respondToExtensionUI("task-1", response);
      await vi.waitFor(() =>
        expect(session.respondToExtensionUI).toHaveBeenCalledOnce(),
      );

      onExtensionError(new Error("subscription closed"));
      expect(
        controller.store.getState().sessions["task-1"].extensionDialogs,
      ).toEqual([request]);
      await vi.advanceTimersByTimeAsync(100);
      await vi.waitFor(() =>
        expect(session.onExtensionEvent).toHaveBeenCalledTimes(2),
      );
      onExtensionEvent({
        type: "extension_state_snapshot",
        dialogs: [request],
        statuses: [],
        widgets: [],
      });

      resolveDelivery();
      await delivery;
      expect(
        controller.store.getState().sessions["task-1"].extensionDialogs,
      ).toEqual([]);
      await controller.respondToExtensionUI("task-1", response);
      expect(session.respondToExtensionUI).toHaveBeenCalledOnce();
      onExtensionEvent({ type: "extension_session_reset" });
    } finally {
      vi.useRealTimers();
    }
  });

  it("does not send another response when expiry races an in-flight response", async () => {
    let onExtensionEvent: (
      event: import("@posthog/agent/pi/types").PiExtensionEvent,
    ) => void = () => {};
    let resolveDelivery: () => void = () => {};
    const session = createSession();
    session.respondToExtensionUI = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          resolveDelivery = resolve;
        }),
    );
    session.onExtensionEvent = vi.fn((handler) => {
      onExtensionEvent = handler;
      return () => {};
    });
    const controller = createController(session);
    await controller.connect("task-1");
    onExtensionEvent({
      type: "extension_ui_request",
      id: "input-1",
      method: "input",
      title: "Name",
      timeout: 50,
    });

    const manual = controller.respondToExtensionUI("task-1", {
      type: "extension_ui_response",
      id: "input-1",
      value: "Ada",
    });
    await vi.waitFor(() =>
      expect(session.respondToExtensionUI).toHaveBeenCalledOnce(),
    );
    onExtensionEvent({ type: "extension_dialog_expired", id: "input-1" });

    expect(session.respondToExtensionUI).toHaveBeenCalledTimes(1);
    expect(
      controller.store.getState().sessions["task-1"].extensionDialogs,
    ).toEqual([]);
    resolveDelivery();
    await manual;
  });

  it("keeps extension events subscribed while the task view is disconnected", async () => {
    let onExtensionEvent: (
      event: import("@posthog/agent/pi/types").PiExtensionEvent,
    ) => void = () => {};
    const unsubscribeExtension = vi.fn();
    let resolveDelivery: () => void = () => {};
    const session = createSession();
    session.respondToExtensionUI = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          resolveDelivery = resolve;
        }),
    );
    session.onExtensionEvent = vi.fn((handler) => {
      onExtensionEvent = handler;
      return unsubscribeExtension;
    });
    const controller = createController(session);

    await controller.connect("task-1");
    onExtensionEvent({
      type: "extension_ui_request",
      id: "confirm-before-away",
      method: "confirm",
      title: "Continue?",
      message: "Proceed?",
    });
    const delivery = controller.respondToExtensionUI("task-1", {
      type: "extension_ui_response",
      id: "confirm-before-away",
      confirmed: true,
    });
    await vi.waitFor(() =>
      expect(session.respondToExtensionUI).toHaveBeenCalledOnce(),
    );
    controller.disconnect("task-1");
    onExtensionEvent({
      type: "extension_ui_request",
      id: "select-while-away",
      method: "select",
      title: "Choose",
      options: ["A", "B"],
    });

    expect(unsubscribeExtension).not.toHaveBeenCalled();
    resolveDelivery();
    await delivery;
    expect(
      controller.store
        .getState()
        .sessions["task-1"].extensionDialogs.map((dialog) => dialog.id),
    ).toEqual(["select-while-away"]);
    await controller.connect("task-1");
    expect(session.onExtensionEvent).toHaveBeenCalledOnce();
  });

  it("clears extension state and subscriptions on session replacement", async () => {
    let onExtensionEvent: (
      event: import("@posthog/agent/pi/types").PiExtensionEvent,
    ) => void = () => {};
    const unsubscribeExtension = vi.fn();
    const session = createSession();
    session.onExtensionEvent = vi.fn((handler) => {
      onExtensionEvent = handler;
      return unsubscribeExtension;
    });
    const controller = createController(session);

    await controller.connect("task-1");
    onExtensionEvent({
      type: "extension_ui_request",
      id: "dialog-1",
      method: "confirm",
      title: "Continue?",
      message: "Proceed?",
    });
    onExtensionEvent({
      type: "extension_ui_request",
      id: "status-1",
      method: "setStatus",
      statusKey: "build",
      statusText: "Running",
    });
    onExtensionEvent({
      type: "extension_ui_request",
      id: "widget-1",
      method: "setWidget",
      widgetKey: "summary",
      widgetLines: ["content"],
    });
    onExtensionEvent({
      type: "extension_ui_request",
      id: "title-1",
      method: "setTitle",
      title: "Extension title",
    });
    onExtensionEvent({
      type: "extension_ui_request",
      id: "draft-1",
      method: "set_editor_text",
      text: "draft",
    });
    onExtensionEvent({
      type: "extension_ui_request",
      id: "notify-1",
      method: "notify",
      message: "notice",
    });

    await controller.connect("task-1", "run-2");

    expect(unsubscribeExtension).toHaveBeenCalledOnce();
    expect(controller.store.getState().sessions["task-1"]).toMatchObject({
      extensionDialogs: [],
      extensionNotifications: [],
      extensionStatuses: {},
      extensionWidgets: {},
      extensionTitle: undefined,
      extensionEditorText: undefined,
    });
  });

  it("reconnects extension events after a transient subscription error", async () => {
    vi.useFakeTimers();
    try {
      let onExtensionEvent: (
        event: import("@posthog/agent/pi/types").PiExtensionEvent,
      ) => void = () => {};
      let onExtensionError: (error: unknown) => void = () => {};
      const unsubscribeExtension = vi.fn();
      const session = createSession();
      session.onExtensionEvent = vi.fn((handler, errorHandler) => {
        onExtensionEvent = handler;
        onExtensionError = errorHandler;
        return unsubscribeExtension;
      });
      const controller = createController(session);
      const connected = controller.connect("task-1");
      await vi.runAllTimersAsync();
      await connected;

      onExtensionError(new Error("subscription closed"));
      expect(unsubscribeExtension).toHaveBeenCalledOnce();
      await vi.advanceTimersByTimeAsync(100);
      await vi.waitFor(() =>
        expect(session.onExtensionEvent).toHaveBeenCalledTimes(2),
      );
      onExtensionEvent({
        type: "extension_ui_request",
        id: "dialog-after-reconnect",
        method: "input",
        title: "Name",
      });

      expect(
        controller.store
          .getState()
          .sessions["task-1"].extensionDialogs.map((dialog) => dialog.id),
      ).toEqual(["dialog-after-reconnect"]);
      onExtensionEvent({ type: "extension_session_reset" });
      await vi.advanceTimersByTimeAsync(1_000);
      expect(session.onExtensionEvent).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps exponential backoff when reconnects only deliver snapshots", async () => {
    vi.useFakeTimers();
    try {
      let onExtensionEvent: (
        event: import("@posthog/agent/pi/types").PiExtensionEvent,
      ) => void = () => {};
      let onExtensionError: (error: unknown) => void = () => {};
      const session = createSession();
      session.onExtensionEvent = vi.fn((handler, errorHandler) => {
        onExtensionEvent = handler;
        onExtensionError = errorHandler;
        return () => {};
      });
      const controller = createController(session);
      const connected = controller.connect("task-1");
      await vi.runAllTimersAsync();
      await connected;

      onExtensionError(new Error("first failure"));
      await vi.advanceTimersByTimeAsync(100);
      expect(session.onExtensionEvent).toHaveBeenCalledTimes(2);

      onExtensionEvent({
        type: "extension_state_snapshot",
        dialogs: [],
        statuses: [],
        widgets: [],
      });
      onExtensionError(new Error("second failure"));
      await vi.advanceTimersByTimeAsync(199);
      expect(session.onExtensionEvent).toHaveBeenCalledTimes(2);
      await vi.advanceTimersByTimeAsync(1);
      expect(session.onExtensionEvent).toHaveBeenCalledTimes(3);

      onExtensionEvent({
        type: "extension_state_snapshot",
        dialogs: [],
        statuses: [],
        widgets: [],
      });
      onExtensionError(new Error("third failure"));
      await vi.advanceTimersByTimeAsync(399);
      expect(session.onExtensionEvent).toHaveBeenCalledTimes(3);
      await vi.advanceTimersByTimeAsync(1);
      expect(session.onExtensionEvent).toHaveBeenCalledTimes(4);
      expect(
        controller.store.getState().sessions["task-1"].extensionNotifications,
      ).toHaveLength(1);

      controller.disconnect("task-1");
    } finally {
      vi.useRealTimers();
    }
  });

  it.each([
    "timed dialog expiry",
    "status and widget clear",
    "session reset",
  ] as const)(
    "reconciles an empty snapshot after disconnected %s",
    async (scenario) => {
      vi.useFakeTimers();
      try {
        let onExtensionEvent: (
          event: import("@posthog/agent/pi/types").PiExtensionEvent,
        ) => void = () => {};
        let onExtensionError: (error: unknown) => void = () => {};
        const session = createSession();
        session.onExtensionEvent = vi.fn((handler, errorHandler) => {
          onExtensionEvent = handler;
          onExtensionError = errorHandler;
          return () => {};
        });
        const controller = createController(session);
        const connected = controller.connect("task-1");
        await vi.runAllTimersAsync();
        await connected;

        if (scenario !== "status and widget clear") {
          onExtensionEvent({
            type: "extension_ui_request",
            id: "dialog-1",
            method: "input",
            title: "Name",
          });
        }
        if (scenario !== "timed dialog expiry") {
          onExtensionEvent({
            type: "extension_ui_request",
            id: "status-1",
            method: "setStatus",
            statusKey: "build",
            statusText: "Running",
          });
          onExtensionEvent({
            type: "extension_ui_request",
            id: "widget-1",
            method: "setWidget",
            widgetKey: "summary",
            widgetLines: ["content"],
          });
        }
        if (scenario === "session reset") {
          onExtensionEvent({
            type: "extension_ui_request",
            id: "title-1",
            method: "setTitle",
            title: "Old title",
          });
        }

        onExtensionError(new Error("subscription closed"));
        const preserved = controller.store.getState().sessions["task-1"];
        expect(
          preserved.extensionDialogs.length +
            Object.keys(preserved.extensionStatuses).length +
            Object.keys(preserved.extensionWidgets).length,
        ).toBeGreaterThan(0);
        await vi.advanceTimersByTimeAsync(100);
        await vi.waitFor(() =>
          expect(session.onExtensionEvent).toHaveBeenCalledTimes(2),
        );
        onExtensionEvent({
          type: "extension_state_snapshot",
          dialogs: [],
          statuses: [],
          widgets: [],
        });

        expect(controller.store.getState().sessions["task-1"]).toMatchObject({
          extensionDialogs: [],
          extensionStatuses: {},
          extensionWidgets: {},
          extensionTitle: undefined,
          extensionEditorText: undefined,
          extensionNotifications: [
            expect.objectContaining({ notifyType: "error" }),
          ],
        });
        onExtensionEvent({ type: "extension_session_reset" });
      } finally {
        vi.useRealTimers();
      }
    },
  );

  it("cancels a pending extension reconnect when the view disconnects", async () => {
    vi.useFakeTimers();
    try {
      let onExtensionError: (error: unknown) => void = () => {};
      const session = createSession();
      session.onExtensionEvent = vi.fn((_handler, errorHandler) => {
        onExtensionError = errorHandler;
        return () => {};
      });
      const controller = createController(session);
      const connected = controller.connect("task-1");
      await vi.runAllTimersAsync();
      await connected;

      onExtensionError(new Error("subscription closed"));
      controller.disconnect("task-1");
      await vi.advanceTimersByTimeAsync(1_000);

      expect(session.onExtensionEvent).toHaveBeenCalledOnce();
    } finally {
      vi.useRealTimers();
    }
  });

  it("uploads cloud follow-up attachments before sending the native message", async () => {
    const session = createSession();
    session.sendUserMessage = vi.fn(async () => {});
    const prepareCloudPiMessage = vi.fn(async () => ({
      content: "Read this\n\nAttached files:\n- /tmp/cloud/input.txt",
      artifactIds: ["artifact-1"],
    }));
    const controller = createController(session, {
      prepareCloudPiMessage,
    } as unknown as TaskService);

    await controller.connect("task-1", "run-1");
    await controller.submit(
      "task-1",
      'Read this <file path="/tmp/input.txt" />',
      false,
      "steer",
    );

    expect(prepareCloudPiMessage).toHaveBeenCalledWith(
      "task-1",
      "run-1",
      'Read this <file path="/tmp/input.txt" />',
    );
    expect(session.sendUserMessage).toHaveBeenCalledWith(
      "prompt",
      "Read this\n\nAttached files:\n- /tmp/cloud/input.txt",
      ["artifact-1"],
      expect.any(String),
    );
    const messageId = vi.mocked(session.sendUserMessage).mock.calls[0][3];
    expect(
      controller.store.getState().sessions["task-1"].events,
    ).toContainEqual(
      expect.objectContaining({ type: "user_message", id: messageId }),
    );
  });

  it("waits for cloud authentication restoration before sending", async () => {
    let authStatus: "restoring" | "authenticated" = "restoring";
    let onStateChange: (state: { status: "authenticated" }) => void = () => {};
    const authService = {
      getState: vi.fn(() => ({ status: authStatus })),
      on: vi.fn((_event, handler) => {
        onStateChange = handler;
      }),
      off: vi.fn(),
    } as unknown as AuthService;
    const session = createSession();
    session.sendUserMessage = vi.fn(async () => {});
    const controller = createController(
      session,
      {
        prepareCloudPiMessage: vi.fn(async () => ({
          content: "hello",
          artifactIds: [],
        })),
      } as unknown as TaskService,
      authService,
    );

    await controller.connect("task-1", "run-1");
    const submission = controller.submit("task-1", "hello", false, "steer");
    await vi.waitFor(() => {
      expect(controller.store.getState().sessions["task-1"].authRestoring).toBe(
        true,
      );
    });
    expect(session.sendUserMessage).not.toHaveBeenCalled();
    await expect(
      controller.submit("task-1", "second", false, "steer"),
    ).rejects.toMatchObject({
      failure: {
        kind: "authentication",
        recoveryPrompt: "second",
      },
    });

    authStatus = "authenticated";
    onStateChange({ status: "authenticated" });
    await submission;

    expect(session.sendUserMessage).toHaveBeenCalledOnce();
    expect(controller.store.getState().sessions["task-1"].authRestoring).toBe(
      false,
    );
  });

  it("cancels auth-held submissions on disconnect and preserves the prompt", async () => {
    const authService = {
      getState: vi.fn(() => ({ status: "restoring" })),
      on: vi.fn(),
      off: vi.fn(),
    } as unknown as AuthService;
    const session = createSession();
    session.sendUserMessage = vi.fn(async () => {});
    const controller = createController(
      session,
      {} as TaskService,
      authService,
    );

    await controller.connect("task-1", "run-1");
    const submission = controller.submit(
      "task-1",
      "do not lose this",
      false,
      "steer",
    );
    await vi.waitFor(() => {
      expect(controller.store.getState().sessions["task-1"].authRestoring).toBe(
        true,
      );
    });

    controller.disconnect("task-1");

    await expect(submission).rejects.toBeInstanceOf(PiOperationError);
    expect(session.sendUserMessage).not.toHaveBeenCalled();
    expect(controller.store.getState().sessions["task-1"].error).toMatchObject({
      scope: "operation",
      kind: "authentication",
      recoveryPrompt: "do not lose this",
    });
  });

  it("classifies usage limits without failing the session", async () => {
    const session = createSession();
    session.sendUserMessage = vi.fn(async () => {
      throw new Error("Rate limit exceeded: User burst rate limit exceeded");
    });
    const controller = createController(session, {
      prepareCloudPiMessage: vi.fn(async () => ({
        content: "hello",
        artifactIds: [],
      })),
    } as unknown as TaskService);

    await controller.connect("task-1", "run-1");
    await expect(
      controller.submit("task-1", "hello", false, "steer"),
    ).rejects.toBeInstanceOf(PiOperationError);

    expect(controller.store.getState().sessions["task-1"]).toMatchObject({
      connectionState: "connected",
      error: {
        scope: "operation",
        kind: "usage_limit",
        title: "Usage limit reached",
        limitCause: "org_limit",
      },
    });
  });

  it("classifies streamed transient provider errors as retryable", async () => {
    let onEvent: (event: AgentConversationEvent) => void = () => {};
    const session = createSession();
    vi.mocked(session.onConversationEvent).mockImplementation((handler) => {
      onEvent = handler;
      return () => {};
    });
    const controller = createController(session);

    await controller.connect("task-1");
    onEvent({
      type: "runtime_error",
      timestamp: 1,
      errorType: "upstream_timeout",
      message: "API Error: request timed out",
    });

    expect(controller.store.getState().sessions["task-1"].error).toMatchObject({
      scope: "operation",
      kind: "transient",
      title: "Provider temporarily unavailable",
      retryable: true,
    });
    expect(controller.store.getState().sessions["task-1"].connectionState).toBe(
      "connected",
    );
  });

  it("keeps fatal runtime errors in a retryable disconnected state", async () => {
    let onEvent: (event: AgentConversationEvent) => void = () => {};
    const session = createSession();
    vi.mocked(session.onConversationEvent).mockImplementation((handler) => {
      onEvent = handler;
      return () => {};
    });
    const controller = createController(session);

    await controller.connect("task-1");
    onEvent({
      type: "runtime_error",
      timestamp: 1,
      errorType: "agent_error",
      message: "process exited unexpectedly",
    });

    expect(controller.store.getState().sessions["task-1"]).toMatchObject({
      connectionState: "disconnected",
      error: {
        scope: "connection",
        kind: "fatal_session",
        title: "Failed to send message",
        retryable: true,
      },
    });
  });

  it("uses action-specific model errors", async () => {
    const session = createSession();
    vi.mocked(session.client.setModel).mockRejectedValue(
      new Error("Model is unavailable"),
    );
    const controller = createController(session);

    await controller.connect("task-1");
    await expect(
      controller.setModel("task-1", { provider: "posthog", id: "missing" }),
    ).rejects.toBeInstanceOf(PiOperationError);

    expect(controller.store.getState().sessions["task-1"].error).toMatchObject({
      scope: "operation",
      kind: "unknown",
      title: "Failed to change Pi model",
      message: "Model is unavailable",
    });
  });

  it("surfaces compaction failure details and resets compacting state", async () => {
    let onEvent: (event: AgentConversationEvent) => void = () => {};
    const session = createSession();
    vi.mocked(session.onConversationEvent).mockImplementation((handler) => {
      onEvent = handler;
      return () => {};
    });
    const controller = createController(session);

    await controller.connect("task-1");
    onEvent({
      type: "runtime_status",
      timestamp: 1,
      status: "compacting",
    });
    onEvent({
      type: "runtime_status",
      timestamp: 2,
      status: "compacting_failed",
      error: "Summary request timed out",
    });

    expect(controller.store.getState().sessions["task-1"]).toMatchObject({
      status: { isCompacting: false },
      error: {
        scope: "operation",
        title: "Failed to compact Pi context",
        message: "Summary request timed out",
      },
    });
  });

  it("allows only one queued message and keeps it out of the transcript", async () => {
    const session = createSession();
    session.sendUserMessage = vi.fn(async () => {});
    vi.mocked(session.getQueue)
      .mockResolvedValueOnce({ steering: [], followUp: [] })
      .mockResolvedValue({ steering: [], followUp: ["first"] });
    const controller = createController(session, {
      prepareCloudPiMessage: vi.fn(async (_taskId, _runId, content) => ({
        content,
        artifactIds: [],
      })),
    } as unknown as TaskService);

    await controller.connect("task-1", "run-1");
    await controller.submit("task-1", "first", true, "queue");

    expect(controller.store.getState().sessions["task-1"]).toMatchObject({
      events: [],
      queue: { steering: [], followUp: ["first"] },
    });
    await expect(
      controller.submit("task-1", "second", true, "queue"),
    ).rejects.toThrow("Pi already has a queued message");
    expect(session.sendUserMessage).toHaveBeenCalledOnce();
  });

  it("clears the optimistic queue when Pi accepted the message as a prompt", async () => {
    const session = createSession();
    session.sendUserMessage = vi.fn(async () => {});
    const controller = createController(session, {
      prepareCloudPiMessage: vi.fn(async () => ({
        content: "continue",
        artifactIds: [],
      })),
    } as unknown as TaskService);

    await controller.connect("task-1", "run-1");
    await controller.submit("task-1", "continue", true, "queue");

    expect(controller.store.getState().sessions["task-1"].queue).toEqual({
      steering: [],
      followUp: [],
    });
  });

  it("marks a submitted turn as streaming while the command starts", async () => {
    let resolveSend: () => void = () => {};
    const sending = new Promise<void>((resolve) => {
      resolveSend = resolve;
    });
    let onEvent: (event: AgentConversationEvent) => void = () => {};
    const session = createSession();
    session.sendUserMessage = vi.fn(() => sending);
    vi.mocked(session.onConversationEvent).mockImplementation((handler) => {
      onEvent = handler;
      return () => {};
    });
    const controller = createController(session, {
      prepareCloudPiMessage: vi.fn(async () => ({
        content: "hello",
        artifactIds: [],
      })),
    } as unknown as TaskService);

    await controller.connect("task-1", "run-1");
    const submission = controller.submit("task-1", "hello", false, "steer");

    await vi.waitFor(() => {
      expect(
        controller.store.getState().sessions["task-1"].status,
      ).toMatchObject({ isStreaming: true });
    });

    resolveSend();
    await submission;
    expect(controller.store.getState().sessions["task-1"].status).toMatchObject(
      { isStreaming: true },
    );

    onEvent({ type: "turn_completed", timestamp: 2 });

    expect(controller.store.getState().sessions["task-1"].status).toMatchObject(
      { isStreaming: false },
    );
  });

  it("restores a native queue after retry replaces the runtime", async () => {
    let onEvent: (event: AgentConversationEvent) => void = () => {};
    const session = createSession();
    session.retry = vi.fn(async () => {});
    vi.mocked(session.onConversationEvent).mockImplementation((handler) => {
      onEvent = handler;
      return () => {};
    });
    const controller = createController(session);

    await controller.connect("task-1", "run-1");
    onEvent({
      type: "queue_update",
      timestamp: 1,
      steering: ["fix this"],
      followUp: ["then summarize"],
    });

    await controller.retry("task-1");

    expect(session.client.prompt).toHaveBeenCalledWith("fix this");
    expect(session.client.followUp).toHaveBeenCalledWith("then summarize");
  });

  it("does not replay an already restored prompt after a later queue failure", async () => {
    let onEvent: (event: AgentConversationEvent) => void = () => {};
    const session = createSession();
    session.retry = vi.fn(async () => {});
    vi.mocked(session.onConversationEvent).mockImplementation((handler) => {
      onEvent = handler;
      return () => {};
    });
    vi.mocked(session.client.followUp).mockRejectedValueOnce(
      new Error("queue unavailable"),
    );
    const controller = createController(session);

    await controller.connect("task-1", "run-1");
    onEvent({
      type: "queue_update",
      timestamp: 1,
      steering: ["fix this"],
      followUp: ["then summarize"],
    });

    await expect(controller.retry("task-1")).rejects.toThrow(
      "queue unavailable",
    );
    await controller.retry("task-1");

    expect(session.client.prompt).toHaveBeenCalledTimes(1);
  });

  it("does not restore a captured queue after the task disconnects", async () => {
    let resolveRetry: () => void = () => {};
    const retrying = new Promise<void>((resolve) => {
      resolveRetry = resolve;
    });
    let onEvent: (event: AgentConversationEvent) => void = () => {};
    const session = createSession();
    session.retry = vi.fn(() => retrying);
    vi.mocked(session.onConversationEvent).mockImplementation((handler) => {
      onEvent = handler;
      return () => {};
    });
    const controller = createController(session);

    await controller.connect("task-1", "run-1");
    onEvent({
      type: "queue_update",
      timestamp: 1,
      steering: ["already handled"],
      followUp: [],
    });
    const retry = controller.retry("task-1");
    await vi.waitFor(() => expect(session.retry).toHaveBeenCalledOnce());

    controller.disconnect("task-1");
    resolveRetry();
    await retry;

    expect(session.client.prompt).not.toHaveBeenCalled();
  });

  it("retries a cloud session without discarding its transcript", async () => {
    const initialEvent: AgentConversationEvent = {
      type: "assistant_message_chunk",
      timestamp: 1,
      content: { type: "text", text: "existing work" },
    };
    const session = createSession();
    session.retry = vi.fn(async () => {});
    vi.mocked(session.getConversation).mockResolvedValue([initialEvent]);
    const controller = createController(session);

    await controller.connect("task-1", "run-1");
    controller.store.setState((state) => ({
      sessions: {
        ...state.sessions,
        "task-1": {
          ...state.sessions["task-1"],
          connectionState: "disconnected",
          error: {
            id: "connection-error",
            scope: "connection",
            kind: "unknown",
            title: "Connection failed",
            message: "stream dropped",
            retryable: true,
            limitCause: null,
          },
        },
      },
    }));

    await controller.retry("task-1");

    expect(session.retry).toHaveBeenCalledOnce();
    expect(controller.store.getState().sessions["task-1"]).toMatchObject({
      connectionState: "connected",
      events: [initialEvent],
      error: undefined,
    });
  });

  it("does not retry disconnected cloud sessions after their view unmounts", async () => {
    const session = createSession();
    session.retry = vi.fn(async () => {});
    const controller = createController(session);

    await controller.connect("task-1", "run-1");
    controller.store.setState((state) => ({
      sessions: {
        ...state.sessions,
        "task-1": {
          ...state.sessions["task-1"],
          connectionState: "disconnected",
          cloudStatus: "in_progress",
          error: {
            id: "connection-error",
            scope: "connection",
            kind: "unknown",
            title: "Connection failed",
            message: "stream dropped",
            retryable: true,
            limitCause: null,
          },
        },
      },
    }));
    controller.disconnect("task-1");

    controller.retryUnhealthyCloudSessions();

    expect(session.retry).not.toHaveBeenCalled();
  });

  it("deduplicates concurrent retry requests", async () => {
    let resolveRetry: () => void = () => {};
    const session = createSession();
    session.retry = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          resolveRetry = resolve;
        }),
    );
    const controller = createController(session);

    await controller.connect("task-1", "run-1");
    controller.store.setState((state) => ({
      sessions: {
        ...state.sessions,
        "task-1": {
          ...state.sessions["task-1"],
          connectionState: "disconnected",
        },
      },
    }));

    const first = controller.retry("task-1");
    const second = controller.retry("task-1");
    await vi.waitFor(() => expect(session.retry).toHaveBeenCalledOnce());
    resolveRetry();
    await Promise.all([first, second]);
  });

  it("uses the live bash operation without reloading native history", async () => {
    const session = createSession();
    const controller = createController(session);

    await controller.bash("task-1", "printf hello");

    expect(session.client.bash).toHaveBeenCalledWith("printf hello");
    expect(session.getConversation).not.toHaveBeenCalled();
  });

  it("does not mark direct bash events as assistant streaming", async () => {
    let onEvent: (event: AgentConversationEvent) => void = () => {};
    const session = createSession();
    vi.mocked(session.onConversationEvent).mockImplementation((handler) => {
      onEvent = handler;
      return () => {};
    });
    const controller = createController(session);

    await controller.connect("task-1", "run-1");
    onEvent({
      type: "tool_call_started",
      timestamp: 1,
      toolCall: {
        id: "pi-bash-live-1-1",
        title: "printf hello",
        kind: "execute",
        status: "in_progress",
        rawInput: { command: "printf hello" },
        origin: "user_shell",
      },
    });
    onEvent({
      type: "tool_call_updated",
      timestamp: 2,
      toolCall: {
        id: "pi-bash-live-1-1",
        status: "completed",
        origin: "user_shell",
      },
    });

    expect(
      controller.store.getState().sessions["task-1"].status?.isStreaming,
    ).toBe(false);
  });

  it("hydrates cold model controls from persisted native config", async () => {
    const session = {
      ...createSession(),
      persistedConfig: {
        model: { provider: "posthog", id: "claude-opus-4-8" },
        thinkingLevel: "high" as const,
      },
    };
    vi.mocked(session.client.getState).mockResolvedValue({
      thinkingLevel: "high",
      isStreaming: false,
      isCompacting: false,
      steeringMode: "all",
      followUpMode: "all",
      sessionId: "session-1",
      autoCompactionEnabled: true,
      messageCount: 0,
      pendingMessageCount: 0,
    });
    vi.mocked(session.client.getAvailableModels).mockResolvedValue([]);
    vi.mocked(session.client.getAvailableThinkingLevels).mockResolvedValue([]);
    const controller = createController(session);

    await controller.connect("task-1", "run-1");

    expect(controller.store.getState().sessions["task-1"]).toMatchObject({
      status: {
        model: { provider: "posthog", id: "claude-opus-4-8" },
        thinkingLevel: "high",
      },
      models: [{ provider: "posthog", id: "claude-opus-4-8" }],
      thinkingLevels: ["high"],
      modelsLoaded: true,
      thinkingLevelsLoaded: true,
    });
  });

  it("keeps persisted controls when the old sandbox is unavailable", async () => {
    const session = {
      ...createSession(),
      taskRunId: "run-1",
      persistedConfig: {
        model: { provider: "posthog", id: "claude-opus-4-8" },
        thinkingLevel: "high" as const,
      },
    };
    vi.mocked(session.client.getState).mockRejectedValue(
      new Error("No active sandbox for this task run"),
    );
    const controller = createController(session);

    await expect(controller.connect("task-1", "run-1")).rejects.toThrow(
      "No active sandbox",
    );

    expect(controller.store.getState().sessions["task-1"]).toMatchObject({
      status: {
        model: { provider: "posthog", id: "claude-opus-4-8" },
        thinkingLevel: "high",
      },
      models: [{ provider: "posthog", id: "claude-opus-4-8" }],
      thinkingLevels: ["high"],
    });
  });

  it("resumes a terminal cloud run only when a message is submitted", async () => {
    const terminalSession = {
      ...createSession(),
      resumeRequired: true,
      taskRunId: "run-1",
    };
    const resumedSession = createSession();
    const provider = {
      get: vi
        .fn()
        .mockResolvedValueOnce(terminalSession)
        .mockResolvedValue(resumedSession),
    } as PiSessionProvider;
    const resumeCloudPiRun = vi.fn(async () => ({ id: "run-1" }));
    const taskService = { resumeCloudPiRun } as unknown as TaskService;
    const controller = new PiSessionController(provider, taskService);

    await controller.connect("task-1");

    expect(resumeCloudPiRun).not.toHaveBeenCalled();

    await controller.submit("task-1", "continue", false, "steer");

    expect(resumeCloudPiRun).toHaveBeenCalledWith("task-1", "run-1");
    expect(resumedSession.client.prompt).toHaveBeenCalledWith("continue");
  });

  it("applies deferred Pi config before the first resumed prompt", async () => {
    const terminalSession = {
      ...createSession(),
      resumeRequired: true,
      taskRunId: "run-1",
    };
    const resumedSession = createSession();
    const provider = {
      get: vi
        .fn()
        .mockResolvedValueOnce(terminalSession)
        .mockResolvedValue(resumedSession),
    } as PiSessionProvider;
    const resumeCloudPiRun = vi.fn(async () => ({ id: "run-1" }));
    const controller = new PiSessionController(provider, {
      resumeCloudPiRun,
    } as unknown as TaskService);

    await controller.connect("task-1");
    await controller.submit("task-1", "continue", false, "steer", {
      model: { provider: "posthog", id: "gpt-5.6-terra" },
      thinkingLevel: "high",
    });

    expect(resumedSession.client.setModel).toHaveBeenCalledWith(
      "posthog",
      "gpt-5.6-terra",
    );
    expect(resumedSession.client.setThinkingLevel).toHaveBeenCalledWith("high");
    expect(resumedSession.client.prompt).toHaveBeenCalledWith("continue");
    expect(
      vi.mocked(resumedSession.client.setModel).mock.invocationCallOrder[0],
    ).toBeLessThan(
      vi.mocked(resumedSession.client.prompt).mock.invocationCallOrder[0],
    );
  });

  it("resumes and retries a message when the prior sandbox is gone", async () => {
    const staleSession = {
      ...createSession(),
      taskRunId: "run-1",
      sendUserMessage: vi.fn(async () => {
        throw new Error("No active sandbox for this task run");
      }),
    };
    const resumedSession = {
      ...createSession(),
      sendUserMessage: vi.fn(async () => {}),
    };
    const provider = {
      get: vi
        .fn()
        .mockResolvedValueOnce(staleSession)
        .mockResolvedValue(resumedSession),
    } as PiSessionProvider;
    const resumeCloudPiRun = vi.fn(async () => ({ id: "run-2" }));
    const taskService = {
      prepareCloudPiMessage: vi.fn(async () => ({
        content: "continue",
        artifactIds: [],
      })),
      resumeCloudPiRun,
    } as unknown as TaskService;
    const controller = new PiSessionController(provider, taskService);

    await controller.connect("task-1");
    await controller.submit("task-1", "continue", false, "steer");

    expect(resumeCloudPiRun).toHaveBeenCalledWith("task-1", "run-1");
    expect(resumedSession.sendUserMessage).toHaveBeenCalledWith(
      "prompt",
      "continue",
      [],
      expect.any(String),
    );
  });

  it("keeps a connected transcript usable when a command fails", async () => {
    const initialEvent: AgentConversationEvent = {
      type: "user_message",
      id: "message-1",
      timestamp: 1,
      content: [{ type: "text", text: "hello" }],
    };
    const session = createSession();
    vi.mocked(session.getConversation).mockResolvedValue([initialEvent]);
    vi.mocked(session.client.prompt).mockRejectedValue(
      new Error("temporary command failure"),
    );
    const controller = createController(session);

    await controller.connect("task-1");
    await expect(
      controller.submit("task-1", "retry me", false, "steer"),
    ).rejects.toThrow("temporary command failure");

    expect(controller.store.getState().sessions["task-1"]).toMatchObject({
      connectionState: "connected",
      events: [initialEvent],
      error: {
        scope: "operation",
        title: "Failed to send message",
        message: "temporary command failure",
      },
    });
  });

  it("owns and releases the bound session lifetime", async () => {
    const session = createSession();
    const provider: PiSessionProvider = {
      get: vi.fn(async () => session),
    };
    const controller = new PiSessionController(provider, {} as TaskService);

    await controller.ensureConnected("task-1");
    await controller.setThinkingLevel("task-1", "high");

    expect(provider.get).toHaveBeenCalledOnce();

    controller.disconnect("task-1");
    await controller.ensureConnected("task-1");

    expect(provider.get).toHaveBeenCalledTimes(2);
  });

  it("opens cold tasks before connecting", async () => {
    const client = createSession();
    vi.mocked(client.health).mockResolvedValue({ state: "cold" });
    const openTask = vi.fn(async () => ({ success: true }));
    const taskService = { openTask } as unknown as TaskService;
    const controller = createController(client, taskService);

    await controller.ensureConnected("task-1", "run-1");

    expect(openTask).toHaveBeenCalledWith("task-1", "run-1");
    expect(controller.store.getState().sessions["task-1"]).toMatchObject({
      connectionState: "connected",
    });
  });

  it("refreshes native thinking levels after changing models", async () => {
    const session = createSession();
    const client = session.client;
    vi.mocked(client.getState).mockResolvedValue({
      thinkingLevel: "high",
      isStreaming: false,
      isCompacting: false,
      steeringMode: "all",
      followUpMode: "all",
      sessionId: "session-1",
      autoCompactionEnabled: true,
      messageCount: 0,
      pendingMessageCount: 0,
      model: {
        provider: "posthog",
        id: "model-2",
        name: "Model 2",
        api: "anthropic-messages",
        baseUrl: "https://example.com",
        reasoning: true,
        input: ["text"],
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
        contextWindow: 200_000,
        maxTokens: 8_000,
      },
    });
    vi.mocked(client.getAvailableModels).mockResolvedValue([
      {
        provider: "posthog",
        id: "model-1",
        contextWindow: 100_000,
        reasoning: true,
      },
      {
        provider: "posthog",
        id: "model-2",
        contextWindow: 200_000,
        reasoning: true,
      },
    ]);
    vi.mocked(client.getAvailableThinkingLevels).mockResolvedValue([
      "off",
      "low",
      "medium",
      "high",
      "xhigh",
    ]);
    const controller = createController(session);
    await controller.ensureConnected("task-1");

    await controller.setModel("task-1", {
      provider: "posthog",
      id: "model-2",
    });

    const state = controller.store.getState().sessions["task-1"];
    expect(state?.models).toEqual([
      expect.objectContaining({ id: "model-1" }),
      expect.objectContaining({ id: "model-2" }),
    ]);
    expect(state?.thinkingLevels).toEqual([
      "off",
      "low",
      "medium",
      "high",
      "xhigh",
    ]);
  });

  it("loads status, models, and thinking levels independently", async () => {
    let resolveModels: (models: []) => void = () => {};
    const models = new Promise<[]>((resolve) => {
      resolveModels = resolve;
    });
    let resolveThinkingLevels: (levels: ["off", "high"]) => void = () => {};
    const thinkingLevels = new Promise<["off", "high"]>((resolve) => {
      resolveThinkingLevels = resolve;
    });
    const initialEvent: AgentConversationEvent = {
      type: "assistant_thought_chunk",
      timestamp: 1,
      content: { type: "text", text: "working" },
    };
    const client = createSession();
    vi.mocked(client.getConversation).mockResolvedValue([initialEvent]);
    vi.mocked(client.client.getState).mockResolvedValue({
      thinkingLevel: "high",
      isStreaming: true,
      isCompacting: false,
      steeringMode: "all",
      followUpMode: "all",
      sessionId: "session-1",
      autoCompactionEnabled: true,
      messageCount: 1,
      pendingMessageCount: 0,
    });
    vi.mocked(client.client.getAvailableModels).mockReturnValue(models);
    vi.mocked(client.client.getAvailableThinkingLevels).mockReturnValue(
      thinkingLevels,
    );
    const controller = createController(client);

    const connection = controller.connect("task-1");

    await vi.waitFor(() => {
      expect(controller.store.getState().sessions["task-1"]).toMatchObject({
        events: [initialEvent],
        status: { isStreaming: true },
        modelsLoaded: false,
        thinkingLevelsLoaded: false,
      });
    });

    resolveThinkingLevels(["off", "high"]);
    await vi.waitFor(() => {
      expect(controller.store.getState().sessions["task-1"]).toMatchObject({
        modelsLoaded: false,
        thinkingLevels: ["off", "high"],
        thinkingLevelsLoaded: true,
      });
    });

    resolveModels([]);
    await connection;
    expect(controller.store.getState().sessions["task-1"]).toMatchObject({
      models: [],
      modelsLoaded: true,
      thinkingLevelsLoaded: true,
    });
  });

  it("reconciles structurally equal live events included in native history", async () => {
    const nativeEvent: AgentConversationEvent = {
      type: "user_message",
      id: "native-message-id",
      timestamp: 1,
      content: [{ type: "text", text: "hello" }],
      sourceId: "pi-entry-1:0",
    };
    const liveEvent: AgentConversationEvent = {
      ...nativeEvent,
      id: "live-message-id",
      content: [{ type: "text", text: "hello" }],
    };
    let resolveConversation: (events: AgentConversationEvent[]) => void =
      () => {};
    const conversation = new Promise<AgentConversationEvent[]>((resolve) => {
      resolveConversation = resolve;
    });
    let onEvent: (event: AgentConversationEvent) => void = () => {};
    let subscribed = false;
    const session = createSession();
    vi.mocked(session.getConversation).mockReturnValue(conversation);
    vi.mocked(session.onConversationEvent).mockImplementation((handler) => {
      onEvent = handler;
      subscribed = true;
      return () => {};
    });
    const controller = createController(session);

    const connection = controller.connect("task-1");
    await vi.waitFor(() => expect(subscribed).toBe(true));
    onEvent(liveEvent);
    resolveConversation([nativeEvent]);
    await connection;

    expect(controller.store.getState().sessions["task-1"].events).toEqual([
      nativeEvent,
    ]);
  });

  it("does not briefly duplicate retained events during reconnect snapshots", async () => {
    const retainedEvent: AgentConversationEvent = {
      type: "assistant_message_chunk",
      timestamp: 1,
      content: { type: "text", text: "retained" },
      sourceId: "pi-entry-1:0",
    };
    let onEvent: (event: AgentConversationEvent) => void = () => {};
    const session = createSession();
    vi.mocked(session.onConversationEvent).mockImplementation((handler) => {
      onEvent = handler;
      return () => {};
    });
    const controller = createController(session);

    await controller.connect("task-1", "run-1");
    onEvent(retainedEvent);
    controller.disconnect("task-1");

    let resolveConversation: (events: AgentConversationEvent[]) => void =
      () => {};
    vi.mocked(session.getConversation).mockReturnValue(
      new Promise((resolve) => {
        resolveConversation = resolve;
      }),
    );
    const reconnect = controller.connect("task-1", "run-1");
    await vi.waitFor(() =>
      expect(session.onConversationEvent).toHaveBeenCalledTimes(2),
    );
    onEvent(retainedEvent);

    expect(controller.store.getState().sessions["task-1"].events).toEqual([
      retainedEvent,
    ]);

    resolveConversation([retainedEvent]);
    await reconnect;
  });

  it("does not append streamed assistant text already present in native history", async () => {
    const nativeEvent: AgentConversationEvent = {
      type: "assistant_message_chunk",
      timestamp: 1,
      content: { type: "text", text: "hello world" },
      sourceId: "pi-entry-1:0",
    };
    const liveEvent: AgentConversationEvent = {
      type: "assistant_message_chunk",
      timestamp: 1,
      content: { type: "text", text: "world" },
      sourceId: "pi-entry-1:0",
    };
    let resolveConversation: (events: AgentConversationEvent[]) => void =
      () => {};
    const conversation = new Promise<AgentConversationEvent[]>((resolve) => {
      resolveConversation = resolve;
    });
    let onEvent: (event: AgentConversationEvent) => void = () => {};
    let subscribed = false;
    const session = createSession();
    vi.mocked(session.getConversation).mockReturnValue(conversation);
    vi.mocked(session.onConversationEvent).mockImplementation((handler) => {
      onEvent = handler;
      subscribed = true;
      return () => {};
    });
    const controller = createController(session);

    const connection = controller.connect("task-1");
    await vi.waitFor(() => expect(subscribed).toBe(true));
    onEvent(liveEvent);
    resolveConversation([nativeEvent]);
    await connection;

    expect(controller.store.getState().sessions["task-1"].events).toEqual([
      nativeEvent,
    ]);
  });

  it("drops retained live events when reconnecting after disconnect", async () => {
    const liveEvent: AgentConversationEvent = {
      type: "assistant_message_chunk",
      timestamp: 1,
      content: { type: "text", text: "stale" },
    };
    let onEvent: (event: AgentConversationEvent) => void = () => {};
    const session = createSession();
    vi.mocked(session.onConversationEvent).mockImplementation((handler) => {
      onEvent = handler;
      return () => {};
    });
    const controller = createController(session);

    await controller.connect("task-1");
    onEvent(liveEvent);
    controller.disconnect("task-1");
    await controller.connect("task-1");

    expect(controller.store.getState().sessions["task-1"].events).toEqual([]);
  });

  it("tracks native queue updates without adding them to the transcript", async () => {
    let onEvent: (event: AgentConversationEvent) => void = () => {};
    const session = createSession();
    vi.mocked(session.onConversationEvent).mockImplementation((handler) => {
      onEvent = handler;
      return () => {};
    });
    const controller = createController(session);

    await controller.connect("task-1");
    onEvent({
      type: "queue_update",
      timestamp: 1,
      steering: ["fix this"],
      followUp: ["then summarize"],
    });

    expect(controller.store.getState().sessions["task-1"]).toMatchObject({
      events: [],
      queue: {
        steering: ["fix this"],
        followUp: ["then summarize"],
      },
      status: { pendingMessageCount: 2 },
    });
  });

  it("clears the native queue and returns its contents for editing", async () => {
    const session = createSession();
    vi.mocked(session.clearQueue).mockResolvedValue({
      steering: ["fix this"],
      followUp: ["then summarize"],
    });
    const controller = createController(session);

    await controller.connect("task-1");
    const queue = await controller.clearQueue("task-1");

    expect(queue).toEqual({
      steering: ["fix this"],
      followUp: ["then summarize"],
    });
    expect(controller.store.getState().sessions["task-1"].queue).toEqual({
      steering: [],
      followUp: [],
    });
  });

  it("uses live turn completion without reloading native history", async () => {
    const turnCompleted: AgentConversationEvent = {
      type: "turn_completed",
      timestamp: 1,
    };
    let onEvent: (event: AgentConversationEvent) => void = () => {};
    const session = createSession();
    vi.mocked(session.onConversationEvent).mockImplementation((handler) => {
      onEvent = handler;
      return () => {};
    });
    const controller = createController(session);

    await controller.connect("task-1");
    vi.mocked(session.client.getSessionStats).mockResolvedValueOnce({
      sessionFile: undefined,
      sessionId: "session-1",
      userMessages: 1,
      assistantMessages: 1,
      toolCalls: 0,
      toolResults: 0,
      totalMessages: 2,
      tokens: {
        input: 1_000,
        output: 500,
        cacheRead: 0,
        cacheWrite: 0,
        total: 1_500,
      },
      cost: 0.03,
      contextUsage: {
        tokens: 12_000,
        contextWindow: 100_000,
        percent: 12,
      },
    });
    onEvent(turnCompleted);

    await vi.waitFor(() => {
      expect(
        controller.store.getState().sessions["task-1"].stats,
      ).toMatchObject({
        cost: 0.03,
        contextUsage: { tokens: 12_000, contextWindow: 100_000 },
      });
    });
    expect(session.getConversation).toHaveBeenCalledOnce();
    expect(controller.store.getState().sessions["task-1"].events).toEqual([
      turnCompleted,
    ]);
  });

  it("loads session state and appends normalized runtime events", async () => {
    const initialEvent: AgentConversationEvent = {
      type: "assistant_message_chunk",
      timestamp: 1,
      content: { type: "text", text: "hello" },
    };
    const liveEvent: AgentConversationEvent = {
      type: "runtime_status",
      timestamp: 2,
      status: "compacting",
    };
    let onEvent: (event: AgentConversationEvent) => void = () => {};
    const client = createSession();
    vi.mocked(client.getConversation).mockResolvedValue([initialEvent]);
    vi.mocked(client.onConversationEvent).mockImplementation((handler) => {
      onEvent = handler;
      return () => {};
    });
    const controller = createController(client);

    await controller.connect("task-1");
    onEvent(liveEvent);

    expect(controller.store.getState().sessions["task-1"]).toMatchObject({
      events: [initialEvent, liveEvent],
      status: { isCompacting: true },
    });
  });
});
