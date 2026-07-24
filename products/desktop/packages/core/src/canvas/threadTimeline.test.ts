import { describe, expect, it } from "vitest";
import {
  buildThreadTimeline,
  deriveThreadAgentStatus,
  hasAgentMention,
  shouldSuspendThreadSession,
  threadMessageArtifact,
} from "./threadTimeline";

describe("hasAgentMention", () => {
  it.each([
    ["at the start", "@agent investigate this", true],
    ["after other text", "Could you @Agent check this?", true],
    ["inside an email-like token", "person@agent.com", false],
    ["as part of a longer handle", "@agents", false],
    ["without a mention", "human-only note", false],
  ])("detects an agent mention %s", (_name, content, expected) => {
    expect(hasAgentMention(content)).toBe(expected);
  });
});

describe("threadMessageArtifact", () => {
  it("maps a canvas_created message to a canvas artifact", () => {
    expect(
      threadMessageArtifact({
        id: "m1",
        content:
          "[Signups](https://us.posthog.com/code/canvas/c/d) has been created",
        created_at: "2026-07-17T00:00:00Z",
        author_kind: "agent",
        event: "canvas_created",
        payload: {
          canvas_name: "Signups",
          canvas_url: "https://us.posthog.com/code/canvas/c/d",
        },
      }),
    ).toEqual({
      kind: "canvas",
      name: "Signups",
      url: "https://us.posthog.com/code/canvas/c/d",
    });
  });

  it("falls back to a default canvas name and no url", () => {
    expect(
      threadMessageArtifact({
        id: "m1",
        content: "Canvas has been created",
        created_at: "2026-07-17T00:00:00Z",
        author_kind: "agent",
        event: "canvas_created",
        payload: {},
      }),
    ).toEqual({ kind: "canvas", name: "Canvas", url: null });
  });

  it("maps a pr_created message to a pr artifact", () => {
    expect(
      threadMessageArtifact({
        id: "m2",
        content: "Pull request opened",
        created_at: "2026-07-17T00:00:00Z",
        author_kind: "agent",
        event: "pr_created",
        payload: { pr_url: "https://github.com/org/repo/pull/123" },
      }),
    ).toEqual({ kind: "pr", url: "https://github.com/org/repo/pull/123" });
  });

  it.each([
    [
      "a pr_created message without a url",
      {
        id: "m3",
        content: "Pull request opened",
        created_at: "2026-07-17T00:00:00Z",
        author_kind: "agent" as const,
        event: "pr_created",
        payload: {},
      },
    ],
    [
      "a turn_complete message",
      {
        id: "m4",
        content: "@[Casey](casey@example.com) Done.",
        created_at: "2026-07-17T00:00:00Z",
        author_kind: "agent" as const,
        event: "turn_complete",
        payload: { run_id: "run" },
      },
    ],
    [
      "a human message",
      {
        id: "m5",
        content: "Looks good",
        created_at: "2026-07-17T00:00:00Z",
      },
    ],
  ])("returns no artifact for %s", (_name, message) => {
    expect(threadMessageArtifact(message)).toBeNull();
  });
});

describe("buildThreadTimeline", () => {
  it("keeps only human messages and artifacts", () => {
    const timeline = buildThreadTimeline([
      {
        id: "human",
        content: "Kicking this off",
        created_at: "1970-01-01T00:00:00.100Z",
      },
      {
        id: "turn",
        content: "@[Casey](casey@example.com) Shipped it.",
        created_at: "1970-01-01T00:00:00.200Z",
        author_kind: "agent",
        event: "turn_complete",
        payload: { run_id: "run" },
      },
      {
        id: "system",
        content: "Status changed",
        created_at: "1970-01-01T00:00:00.250Z",
        author_kind: "system",
        event: "status_changed",
      },
      {
        id: "canvas",
        content: "Canvas has been created",
        created_at: "1970-01-01T00:00:00.300Z",
        author_kind: "agent",
        event: "canvas_created",
        payload: { canvas_name: "Signups", canvas_url: null },
      },
    ]);

    expect(timeline.map((row) => row.kind)).toEqual(["human", "artifact"]);
  });

  it("orders human messages and artifacts chronologically", () => {
    const timeline = buildThreadTimeline([
      {
        id: "pr",
        content: "Pull request opened",
        created_at: "1970-01-01T00:00:00.200Z",
        author_kind: "agent",
        event: "pr_created",
        payload: { pr_url: "https://github.com/org/repo/pull/1" },
      },
      {
        id: "human",
        content: "Reply",
        created_at: "1970-01-01T00:00:00.100Z",
      },
    ]);

    expect(timeline.map((row) => row.message.id)).toEqual(["human", "pr"]);
  });

  it("keeps malformed timestamps at the end", () => {
    const timeline = buildThreadTimeline([
      { id: "broken", content: "Reply", created_at: "invalid" },
      {
        id: "human",
        content: "Reply",
        created_at: "1970-01-01T00:00:00.100Z",
      },
    ]);

    expect(timeline.map((row) => row.message.id)).toEqual(["human", "broken"]);
  });

  it("exposes the artifact and the source message on artifact rows", () => {
    const [row] = buildThreadTimeline([
      {
        id: "pr",
        content: "Pull request opened",
        created_at: "1970-01-01T00:00:00.200Z",
        author_kind: "agent",
        event: "pr_created",
        payload: { pr_url: "https://github.com/org/repo/pull/1" },
      },
    ]);

    expect(row).toMatchObject({
      kind: "artifact",
      artifact: { kind: "pr", url: "https://github.com/org/repo/pull/1" },
      message: { id: "pr" },
    });
  });
});

describe("deriveThreadAgentStatus", () => {
  it.each([
    {
      name: "returns no status before activity",
      input: {},
      expected: null,
    },
    {
      name: "prioritizes failures",
      input: { hasActivity: true, hasError: true, errorTitle: "Run failed" },
      expected: { phase: "error", label: "Run failed" },
    },
    {
      name: "prioritizes pending permissions over active work",
      input: {
        hasActivity: true,
        pendingPermissionCount: 1,
        isPromptPending: true,
      },
      expected: { phase: "needs_input", label: "Needs input" },
    },
    {
      name: "reports active work",
      input: { hasActivity: true, isPromptPending: true },
      expected: { phase: "active", label: "Working…" },
    },
    {
      name: "returns no status after work settles",
      input: { hasActivity: true },
      expected: null,
    },
  ])("$name", ({ input, expected }) => {
    expect(deriveThreadAgentStatus(input)).toEqual(expected);
  });
});

describe("shouldSuspendThreadSession", () => {
  it("suspends a local runless task so reading cannot start work", () => {
    expect(
      shouldSuspendThreadSession({
        isCloud: false,
        hasRun: false,
        hasSession: false,
      }),
    ).toBe(true);
  });

  it.each([
    { isCloud: true, hasRun: false, hasSession: false },
    { isCloud: false, hasRun: true, hasSession: false },
    { isCloud: false, hasRun: false, hasSession: true },
  ])("keeps an existing or cloud session attached", (input) => {
    expect(shouldSuspendThreadSession(input)).toBe(false);
  });
});
