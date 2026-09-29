import type { StoredLogEntry } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import { transcriptFrom, withPending } from "./transcript";

const at = (second: number): string =>
  new Date(Date.UTC(2026, 0, 1, 0, 0, second)).toISOString();

const piEvent = (
  second: number,
  event: Record<string, unknown>,
): StoredLogEntry =>
  ({
    type: "pi_event",
    timestamp: at(second),
    event: { timestamp: second * 1000, ...event },
  }) as StoredLogEntry;

const PI_LOG: StoredLogEntry[] = [
  { type: "pi_run_started", timestamp: at(0) },
  piEvent(1, {
    type: "user_message",
    id: "u1",
    content: [{ type: "text", text: "Rename the helper" }],
  }),
  piEvent(2, {
    type: "assistant_message_chunk",
    content: { type: "text", text: "On it. " },
  }),
  piEvent(3, {
    type: "assistant_message_chunk",
    content: { type: "text", text: "Renaming now." },
  }),
  piEvent(4, {
    type: "tool_call_started",
    toolCall: {
      id: "t1",
      title: "Edit src/a.ts",
      kind: "edit",
      status: "pending",
    },
  }),
  piEvent(5, {
    type: "tool_call_updated",
    toolCall: { id: "t1", status: "completed" },
  }),
  piEvent(6, { type: "turn_completed", stopReason: "stop" }),
];

const acp = (
  second: number,
  notification: Record<string, unknown>,
): StoredLogEntry =>
  ({
    type: "notification",
    timestamp: at(second),
    notification: { jsonrpc: "2.0", ...notification },
  }) as StoredLogEntry;
const update = (
  second: number,
  sessionUpdate: Record<string, unknown>,
): StoredLogEntry =>
  acp(second, { method: "session/update", params: { update: sessionUpdate } });

const ACP_LOG: StoredLogEntry[] = [
  acp(1, {
    id: 1,
    method: "session/prompt",
    params: { prompt: [{ type: "text", text: "Rename the helper" }] },
  }),
  update(2, {
    sessionUpdate: "agent_message_chunk",
    content: { type: "text", text: "On it. " },
  }),
  update(3, {
    sessionUpdate: "agent_message_chunk",
    content: { type: "text", text: "Renaming now." },
  }),
  update(4, {
    sessionUpdate: "tool_call",
    toolCallId: "t1",
    title: "Edit src/a.ts",
    kind: "edit",
    status: "pending",
  }),
  update(5, {
    sessionUpdate: "tool_call_update",
    toolCallId: "t1",
    status: "completed",
  }),
  acp(6, { id: 1, result: { stopReason: "end_turn" } }),
];

describe("transcriptFrom", () => {
  it.each([
    ["pi", PI_LOG],
    ["acp", ACP_LOG],
  ] as const)(
    "reads a %s run's log into the same transcript",
    (runtime, entries) => {
      const lines = transcriptFrom(runtime, entries).lines.map(
        ({ id: _, ...line }) => line,
      );
      expect(lines).toEqual([
        { kind: "user", text: "Rename the helper" },
        { kind: "assistant", text: "On it. Renaming now." },
        { kind: "tool", title: "Edit src/a.ts", status: "completed" },
      ]);
    },
  );

  it("shows a new pi chat's first message before the sandbox echoes it, and only once after", () => {
    expect(
      transcriptFrom("pi", [], "Fix the flaky test").lines.map(
        ({ id: _, ...line }) => line,
      ),
    ).toEqual([{ kind: "user", text: "Fix the flaky test" }]);
    const echoed = transcriptFrom(
      "pi",
      PI_LOG,
      "Rename the helper",
    ).lines.filter((line) => line.kind === "user");
    expect(echoed).toHaveLength(1);
  });
});

describe("transcriptFrom turn state", () => {
  it.each([
    ["mid-turn", PI_LOG.slice(0, -1), true],
    ["after the turn completed", PI_LOG, false],
    ["before any turn", [], false],
  ])("reports whether the agent is %s", (_, entries, open) => {
    expect(transcriptFrom("pi", entries).turnOpen).toBe(open);
  });
});

describe("withPending", () => {
  const user = (text: string) => ({ kind: "user" as const, id: text, text });
  const reply = { kind: "assistant" as const, id: "a", text: "Done" };

  it.each([
    ["nothing is pending", [user("hi"), reply], null, ["hi", "Done"]],
    [
      "a sent message has not come back yet",
      [user("hi"), reply],
      "and then?",
      ["hi", "Done", "and then?"],
    ],
    [
      "the run has echoed it",
      [user("hi"), reply, user("and then?")],
      "and then?",
      ["hi", "Done", "and then?"],
    ],
    ["a new chat has no log yet", [], "Fix it", ["Fix it"]],
  ])("when %s", (_, lines, pending, expected) => {
    expect(
      withPending(lines, pending).map((line) =>
        "text" in line ? line.text : "",
      ),
    ).toEqual(expected);
  });
});
