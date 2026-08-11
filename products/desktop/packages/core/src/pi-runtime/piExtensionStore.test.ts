import type { PiExtensionEvent } from "@posthog/agent/pi/types";
import { describe, expect, it } from "vitest";
import {
  createEmptyPiExtensionTaskState,
  type PiExtensionTaskState,
  reducePiExtensionState,
} from "./piExtensionStore";

describe("reducePiExtensionState", () => {
  it("applies and clears non-dialog extension surfaces", () => {
    const events: PiExtensionEvent[] = [
      {
        type: "extension_ui_request",
        id: "notify-1",
        method: "notify",
        message: "Finished",
        notifyType: "warning",
      },
      {
        type: "extension_ui_request",
        id: "status-1",
        method: "setStatus",
        statusKey: "build",
        statusText: "Running",
      },
      {
        type: "extension_ui_request",
        id: "widget-1",
        method: "setWidget",
        widgetKey: "summary",
        widgetLines: ["Ready"],
        widgetPlacement: "belowEditor",
      },
      {
        type: "extension_ui_request",
        id: "title-1",
        method: "setTitle",
        title: "Extension task",
      },
      {
        type: "extension_error",
        extensionPath: "/extensions/example.ts",
        event: "tool_call",
        error: "boom",
      },
    ];

    const state = events.reduce<PiExtensionTaskState>(
      (current, event) =>
        reducePiExtensionState(current, {
          type: "event",
          event,
          id: event.type === "extension_error" ? "error-1" : event.id,
        }),
      createEmptyPiExtensionTaskState(),
    );

    expect(state).toMatchObject({
      notifications: [
        {
          id: "notify-1",
          message: "Finished",
          notifyType: "warning",
        },
        {
          id: "error-1",
          message: "example.ts failed during tool_call: boom",
          notifyType: "error",
        },
      ],
      statuses: { build: "Running" },
      widgets: {
        summary: { lines: ["Ready"], placement: "belowEditor" },
      },
      title: "Extension task",
    });

    const statusCleared = reducePiExtensionState(state, {
      type: "event",
      id: "status-clear",
      event: {
        type: "extension_ui_request",
        id: "status-clear",
        method: "setStatus",
        statusKey: "build",
        statusText: undefined,
      },
    });
    const surfacesCleared = reducePiExtensionState(statusCleared, {
      type: "event",
      id: "widget-clear",
      event: {
        type: "extension_ui_request",
        id: "widget-clear",
        method: "setWidget",
        widgetKey: "summary",
        widgetLines: undefined,
      },
    });

    expect(surfacesCleared.statuses).toEqual({});
    expect(surfacesCleared.widgets).toEqual({});
  });
});
