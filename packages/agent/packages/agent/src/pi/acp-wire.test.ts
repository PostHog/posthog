import { describe, expect, it } from "vitest";
import {
  type PiExtensionDialog,
  piAcpLogEntries,
  piAcpWireEntry,
  piExtensionDialogResponse,
} from "./acp-wire";

function notificationOf(entry: Record<string, unknown>) {
  return (
    piAcpWireEntry(entry) as {
      notification?: { method?: string; params?: Record<string, unknown> };
    } | null
  )?.notification;
}

describe("piAcpWireEntry", () => {
  it.each([
    {
      caseName: "a tool start whose title only repeats the tool name",
      toolCall: {
        id: "t1",
        name: "read",
        title: "read",
        kind: "read",
        _meta: { posthog: { toolName: "Read" } },
      },
      expected: {
        sessionUpdate: "tool_call",
        toolCallId: "t1",
        name: "read",
        kind: "read",
        _meta: { posthog: { toolName: "Read" } },
      },
    },
    {
      caseName: "a user shell command, which keeps its command as the title",
      toolCall: { id: "pi-bash-1", title: "ls", kind: "execute" },
      expected: {
        sessionUpdate: "tool_call",
        toolCallId: "pi-bash-1",
        title: "ls",
        kind: "execute",
      },
    },
  ])("writes $caseName as a session update", ({ toolCall, expected }) => {
    expect(
      piAcpWireEntry({
        type: "pi_event",
        id: "entry-1",
        timestamp: "2026-01-01T00:00:00Z",
        event_id: "boot-3",
        covered_event_ids: ["boot-1"],
        event: { type: "tool_call_started", timestamp: 1, toolCall },
      }),
    ).toEqual({
      type: "notification",
      id: "entry-1",
      timestamp: "2026-01-01T00:00:00Z",
      event_id: "boot-3",
      covered_event_ids: ["boot-1"],
      notification: {
        jsonrpc: "2.0",
        method: "session/update",
        params: { update: expected },
      },
    });
  });

  it.each([
    {
      caseName: "run start marker",
      entry: { type: "pi_run_started", runId: "run-1", taskId: "task-1" },
      method: "_posthog/run_started",
    },
    {
      caseName: "persisted extension request",
      entry: {
        type: "pi_extension_event",
        notification: {
          method: "_posthog/pi_extension_event",
          params: {
            type: "extension_ui_request",
            id: "e1",
            method: "select",
            title: "Pick",
            options: ["A", "B"],
          },
        },
      },
      method: "_posthog/permission_request",
    },
    {
      caseName: "live extension response",
      entry: { type: "extension_ui_response", id: "e1", value: "A" },
      method: "_posthog/permission_resolved",
    },
    {
      caseName: "fire-and-forget notify",
      entry: {
        type: "extension_ui_request",
        id: "e2",
        method: "notify",
        message: "Saved",
      },
      method: "_posthog/console",
    },
    {
      caseName: "widget update",
      entry: {
        type: "extension_ui_request",
        id: "e3",
        method: "setStatus",
        statusKey: "lint",
        statusText: "ok",
      },
      method: "_posthog/pi_extension_event",
    },
  ])("translates a $caseName into $method", ({ entry, method }) => {
    expect(notificationOf(entry)?.method).toBe(method);
  });

  it.each([
    {
      caseName: "a warning notification",
      entry: {
        type: "extension_ui_request",
        id: "e3",
        method: "notify",
        message: "Lint warnings",
        notifyType: "warning",
      },
      message: "Lint warnings",
    },
    {
      caseName: "an extension failure",
      entry: {
        type: "extension_error",
        extensionPath: "/ext/lint.ts",
        event: "tool_call",
        error: "crashed",
      },
      message: "lint.ts failed during tool_call: crashed",
    },
  ])(
    "shows $caseName as a notice that carries the Pi message",
    ({ entry, message }) => {
      expect(notificationOf(entry)).toEqual({
        jsonrpc: "2.0",
        method: "_posthog/status",
        params: {
          status: "extension_notice",
          isComplete: true,
          message,
          _meta: { piExtension: entry },
        },
      });
    },
  );

  it.each([
    {
      method: "input",
      fields: { placeholder: "Branch name" },
      expected: { placeholder: "Branch name" },
    },
    {
      method: "editor",
      fields: { prefill: "Line one\nLine two" },
      expected: { defaultAnswer: "Line one\nLine two", multiline: true },
    },
  ])(
    "carries the $method prompt defaults onto its question",
    ({ method, fields, expected }) => {
      expect(
        notificationOf({
          type: "extension_ui_request",
          id: "e1",
          method,
          title: "Branch?",
          ...fields,
        })?.params,
      ).toMatchObject({
        toolCall: {
          _meta: {
            questions: [{ question: "Branch?", options: [], ...expected }],
          },
        },
      });
    },
  );

  it("passes an entry that is already ACP through unchanged", () => {
    const entry = {
      type: "notification",
      notification: { method: "_posthog/usage_update", params: {} },
    };
    expect(piAcpWireEntry(entry)).toBe(entry);
  });
});

describe("piExtensionDialogResponse", () => {
  const confirm: PiExtensionDialog = {
    id: "e1",
    method: "confirm",
    options: [],
  };
  const input: PiExtensionDialog = { id: "e1", method: "input", options: [] };
  const select: PiExtensionDialog = {
    id: "e1",
    method: "select",
    options: ["A", "B"],
  };

  it.each([
    {
      caseName: "a confirmed prompt",
      dialog: confirm,
      answer: { optionId: "confirm" },
      expected: { type: "extension_ui_response", id: "e1", confirmed: true },
    },
    {
      caseName: "a cancelled prompt",
      dialog: confirm,
      answer: { optionId: "cancel" },
      expected: { type: "extension_ui_response", id: "e1", cancelled: true },
    },
    {
      caseName: "an answered question",
      dialog: input,
      answer: { optionId: "option_0", answers: { "Branch?": "feat/x" } },
      expected: { type: "extension_ui_response", id: "e1", value: "feat/x" },
    },
    {
      caseName: "a picked option",
      dialog: select,
      answer: { optionId: "option_1" },
      expected: { type: "extension_ui_response", id: "e1", value: "B" },
    },
  ])("answers $caseName", ({ dialog, answer, expected }) => {
    expect(piExtensionDialogResponse(dialog, answer)).toEqual(expected);
  });
});

describe("piAcpLogEntries", () => {
  const chunk = (text: string, eventId: string) => ({
    type: "pi_event",
    id: `entry-${eventId}`,
    event_id: eventId,
    timestamp: "2026-01-01T00:00:00Z",
    event: {
      type: "assistant_message_chunk",
      timestamp: 1,
      content: { type: "text", text },
    },
  });

  it.each([
    { final: false, written: [], carried: 2 },
    { final: true, written: ["pong"], carried: 0 },
  ])(
    "holds back a message still streaming unless the flush is final ($final)",
    ({ final, written, carried }) => {
      const { wire, carry } = piAcpLogEntries(
        [chunk("po", "boot-1"), chunk("ng", "boot-2")],
        { final },
      );
      expect(
        wire.map(
          (entry) =>
            (
              entry.notification?.params as {
                update: { content: { text: string } };
              }
            ).update.content.text,
        ),
      ).toEqual(written);
      expect(carry).toHaveLength(carried);
    },
  );
});
