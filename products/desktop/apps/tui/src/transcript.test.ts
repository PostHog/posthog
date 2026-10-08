import type { StoredLogEntry } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import {
  activityOf,
  type ToolLine,
  type TranscriptLine,
  toolSummary,
  transcriptFrom,
  withPending,
  withPendingShells,
} from "./transcript";

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
      rawInput: { path: "src/a.ts" },
    },
  }),
  piEvent(5, {
    type: "tool_call_updated",
    toolCall: {
      id: "t1",
      status: "completed",
      rawOutput: [{ type: "text", text: "Renamed 3 uses" }],
    },
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
    rawInput: { path: "src/a.ts" },
  }),
  update(5, {
    sessionUpdate: "tool_call_update",
    toolCallId: "t1",
    status: "completed",
    content: [
      { type: "content", content: { type: "text", text: "Renamed 3 uses" } },
    ],
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
        {
          kind: "tool",
          title: "Edit src/a.ts",
          tool: "edit",
          status: "completed",
          detail: "src/a.ts",
          output: "Renamed 3 uses",
        },
      ]);
    },
  );

  it("keeps the images a pi message was sent with on its user line", () => {
    const image = { type: "image", data: "aGk=", mimeType: "image/png" };
    const lines = transcriptFrom("pi", [
      piEvent(1, {
        type: "user_message",
        id: "u1",
        content: [{ type: "text", text: "look at [Image #2]" }, image],
      }),
      piEvent(2, {
        type: "user_message",
        id: "u2",
        content: [{ type: "text", text: "and nothing here" }],
      }),
    ]).lines.filter((line) => line.kind === "user");

    expect(lines.map((line) => line.kind === "user" && line.images)).toEqual([
      [{ data: "aGk=", mimeType: "image/png" }],
      undefined,
    ]);
  });

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

describe("transcriptFrom shell commands", () => {
  const PI_TRANSCRIPT = transcriptFrom("pi", PI_LOG).lines;
  // The shape pi's saved conversation gives a command the user ran with !.
  const userShell = (second: number, command: string, output: string) => [
    piEvent(second, {
      type: "tool_call_started",
      toolCall: {
        id: `pi-bash-${second * 1000}`,
        title: command,
        kind: "execute",
        status: "in_progress",
        rawInput: { command },
        origin: "user_shell",
      },
    }),
    piEvent(second, {
      type: "tool_call_updated",
      toolCall: {
        id: `pi-bash-${second * 1000}`,
        status: "completed",
        rawOutput: output,
        origin: "user_shell",
        content: [{ type: "content", content: { type: "text", text: output } }],
      },
    }),
  ];

  it("shows a command the user ran apart from the agent's own tool calls", () => {
    const { lines } = transcriptFrom("pi", [
      ...PI_LOG,
      ...userShell(7, "git status", "clean"),
    ]);

    expect(lines.map((line) => line.kind)).toEqual([
      "user",
      "assistant",
      "tool",
      "shell",
    ]);
    expect(lines.at(-1)).toEqual({
      kind: "shell",
      id: expect.any(String),
      command: "git status",
      status: "completed",
      output: "clean",
    });
  });

  it("keeps a command shown until the run's log has it, then shows it once", () => {
    const line = {
      kind: "shell" as const,
      id: "pending-shell",
      command: "git status",
      status: "completed",
      output: "clean",
    };
    const shells = (lines: TranscriptLine[]) =>
      lines.filter((candidate) => candidate.kind === "shell");
    const once = transcriptFrom("pi", [
      ...PI_LOG,
      ...userShell(7, "git status", "clean"),
    ]).lines;
    const twice = transcriptFrom("pi", [
      ...PI_LOG,
      ...userShell(7, "git status", "clean"),
      ...userShell(8, "git status", "clean"),
    ]).lines;
    const first = { line, seen: 0 };
    const second = { line: { ...line, id: "again" }, seen: 1 };

    expect(withPendingShells(PI_TRANSCRIPT, [first]).at(-1)).toEqual(line);
    expect(shells(withPendingShells(once, [first]))).toHaveLength(1);
    // Running the same command again waits for its own log entry, not the first one's.
    expect(shells(withPendingShells(once, [second]))).toHaveLength(2);
    expect(shells(withPendingShells(twice, [second]))).toHaveLength(2);
  });
});

describe("transcriptFrom compaction", () => {
  const lines = (entries: StoredLogEntry[]) =>
    transcriptFrom("pi", entries).lines.map(({ id: _, ...line }) => line);
  const compaction = (
    second: number,
    reason: string,
    end?: { tokensBefore?: number; estimatedTokensAfter?: number },
  ): StoredLogEntry[] => [
    piEvent(second, {
      type: "runtime_status",
      status: "compacting",
      compaction: {
        reason,
        ...(reason === "manual" ? { instructions: "keep the plan" } : {}),
      },
    }),
    piEvent(second + 1, {
      type: "runtime_status",
      status: "compacting",
      isComplete: true,
      compaction: { reason, ...end },
    }),
    piEvent(second + 1, {
      type: "assistant_message_chunk",
      content: { type: "text", text: "## Goal\nThe whole summary" },
    }),
  ];

  it.each([
    [
      "a /compact as sent, then what it freed",
      compaction(1, "manual", {
        tokensBefore: 1_240_000,
        estimatedTokensAfter: 32_000,
      }),
      [
        { kind: "user", text: "/compact keep the plan" },
        { kind: "notice", text: "Compacted 1.2M → ~32k tokens", tone: "info" },
      ],
    ],
    [
      "an automatic one as a notice alone",
      compaction(1, "threshold", { tokensBefore: 180_000 }),
      [
        {
          kind: "notice",
          text: "Compacted automatically: 180k tokens",
          tone: "info",
        },
      ],
    ],
    [
      "one from a run that predates the sizes",
      compaction(1, "manual").map((entry) => {
        const { compaction: _, ...event } = (entry as { event: object })
          .event as { compaction?: unknown };
        return { ...entry, event } as StoredLogEntry;
      }),
      [{ kind: "notice", text: "Compacted", tone: "info" }],
    ],
    [
      "nothing freed by one that stopped",
      compaction(1, "threshold").slice(0, 2),
      [],
    ],
  ])("shows %s, without the summary", (_, entries, expected) => {
    expect(lines(entries)).toEqual(expected);
  });
});

describe("transcriptFrom bookkeeping", () => {
  it("hides the agent's task summary updates", () => {
    const entries = [
      ...PI_LOG.slice(0, 2),
      piEvent(3, {
        type: "tool_call_started",
        toolCall: {
          id: "s1",
          title: "mcp_posthog_code_tools_task_summary_update",
          status: "completed",
        },
      }),
    ];
    expect(
      transcriptFrom("pi", entries).lines.map((line) => line.kind),
    ).toEqual(["user"]);
  });
});

describe("transcriptFrom actions", () => {
  it("turns a show_actions call into an actions line and drops calls it cannot read", () => {
    const actions = [
      {
        kind: "compose",
        label: "Try again in a new task",
        prompt: "Add tracing",
      },
    ];
    const entries = [
      ...PI_LOG.slice(0, 2),
      piEvent(3, {
        type: "tool_call_started",
        toolCall: {
          id: "x1",
          title: "mcp_posthog_code_tools_show_actions",
          status: "failed",
          rawInput: { actions: [] },
        },
      }),
      piEvent(4, {
        type: "tool_call_started",
        toolCall: {
          id: "x2",
          title: "mcp_posthog_code_tools_show_actions",
          status: "completed",
          rawInput: { actions },
        },
      }),
    ];
    const lines = transcriptFrom("pi", entries).lines;

    expect(lines.map((line) => line.kind)).toEqual(["user", "actions"]);
    expect(lines[1]).toMatchObject({ kind: "actions", actions });
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

  it("keeps a turn open when the log window starts after its prompt", () => {
    const transcript = transcriptFrom("acp", ACP_LOG.slice(1, -1));
    expect(transcript.turnOpen).toBe(true);
    expect(transcript.turnStartedAt).toBe(new Date(at(2)).getTime());
    expect(transcript.lastTurn).toBeNull();
  });
});

describe("transcriptFrom last turn", () => {
  it("reports how long a finished turn took and when it ended", () => {
    expect(transcriptFrom("pi", PI_LOG).lastTurn).toEqual({
      durationMs: 5000,
      endedAt: 6000,
      stopReason: "stop",
    });
    expect(transcriptFrom("pi", PI_LOG.slice(0, -1)).lastTurn).toBeNull();
  });

  it("reports the wake-up the agent scheduled at the end of the turn", () => {
    const wake = update(5, {
      sessionUpdate: "tool_call",
      toolCallId: "w1",
      title: "ScheduleWakeup",
      kind: "other",
      status: "completed",
      rawInput: { delaySeconds: 300, reason: "watching CI" },
      rawOutput: { scheduledFor: 305_000 },
    });
    const log = [...ACP_LOG.slice(0, -1), wake, ACP_LOG.at(-1)!];
    expect(transcriptFrom("acp", log).wake).toEqual({
      at: 305_000,
      reason: "watching CI",
    });
    expect(transcriptFrom("acp", ACP_LOG).wake).toBeNull();
    expect(transcriptFrom("acp", log.slice(0, -1)).wake).toBeNull();
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

describe("toolSummary", () => {
  it("counts Claude Code's calls by what they did, not by their descriptions", () => {
    const line = (title: string, tool: string): ToolLine => ({
      kind: "tool",
      id: title,
      title,
      tool,
      status: "completed",
      detail: "",
      output: "",
    });
    expect(
      toolSummary([
        line("Probe tools and conventions", "execute"),
        line("Find lint on receivers", "execute"),
        line("Read the isolation linter", "read"),
        line("Look up the docs", "fetch"),
      ]),
    ).toBe("Ran 2 shell commands · read 1 file · fetched 1 page");
    expect(activityOf(line("Probe tools", "execute"))).toBe("Running");
  });

  const call = (title: string): ToolLine => ({
    kind: "tool",
    id: title,
    title,
    status: "completed",
    detail: "",
    output: "",
  });

  it.each([
    [["bash"], "Ran 1 shell command"],
    [["bash", "read", "bash", "read"], "Ran 2 shell commands · read 2 files"],
    [["edit", "write"], "Edited 2 files"],
    [["posthog__exec", "posthog__exec"], "Called PostHog 2 times"],
  ])("sums up %j as %s", (titles, expected) => {
    expect(toolSummary(titles.map(call))).toBe(expected);
  });
});
