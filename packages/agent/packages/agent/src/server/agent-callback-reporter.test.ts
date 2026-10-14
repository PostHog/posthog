import { describe, expect, it, vi } from "vitest";
import { Logger } from "../utils/logger";
import {
  type AgentCallback,
  AgentCallbackReporter,
  createAgentCallbackReporter,
} from "./agent-callback-reporter";

type Event = Record<string, unknown>;

const sessionUpdate = (kind: string): Event => ({
  type: "notification",
  notification: {
    method: "session/update",
    params: { update: { sessionUpdate: kind } },
  },
});

const turnComplete = (stopReason: string): Event => ({
  type: "notification",
  notification: { method: "_posthog/turn_complete", params: { stopReason } },
});

const piEvent = (event: Event): Event => ({ type: "pi_event", event });

const ingestToken = (claims: Event): string =>
  `header.${Buffer.from(JSON.stringify(claims)).toString("base64url")}.signature`;

function createReporter(
  send: (callback: AgentCallback) => Promise<boolean> = async () => true,
) {
  const sent: AgentCallback[] = [];
  const clock = { nowMs: 0 };
  const reporter = new AgentCallbackReporter({
    send: async (callback) => {
      sent.push(callback);
      return send(callback);
    },
    logger: new Logger({ debug: false }),
    now: () => clock.nowMs,
    retryDelayMs: 0,
  });
  return { reporter, sent, clock };
}

describe("AgentCallbackReporter", () => {
  it.each([
    {
      name: "a successful turn",
      event: turnComplete("end_turn"),
      expected: {
        kind: "awaiting_input",
        agent_active: false,
        turn_completed: true,
        turn_succeeded: true,
      },
    },
    {
      name: "a cancelled turn",
      event: turnComplete("cancelled"),
      expected: {
        kind: "awaiting_input",
        agent_active: false,
        turn_completed: true,
        turn_succeeded: false,
      },
    },
    {
      name: "an idle sandbox resume",
      event: turnComplete("idle_resume"),
      expected: {
        kind: "awaiting_input",
        agent_active: false,
        turn_completed: false,
        turn_succeeded: false,
      },
    },
    {
      name: "a raw prompt response",
      event: {
        type: "notification",
        notification: { result: { stopReason: "end_turn" } },
      },
      expected: {
        kind: "awaiting_input",
        agent_active: false,
        turn_completed: true,
        turn_succeeded: true,
      },
    },
    {
      name: "a successful Pi turn",
      event: piEvent({ type: "turn_completed", stopReason: "end_turn" }),
      expected: {
        kind: "awaiting_input",
        agent_active: false,
        turn_completed: true,
        turn_succeeded: true,
      },
    },
  ])("reports $name", async ({ event, expected }) => {
    const { reporter, sent } = createReporter();

    reporter.observe(event, true);
    await reporter.settled();

    expect(sent).toEqual([expected]);
  });

  it("reports a Pi runtime error only after the stream accepted the event", async () => {
    const { reporter, sent } = createReporter();
    const failure = piEvent({ type: "turn_completed", stopReason: "error" });

    reporter.observe(failure, true);
    await reporter.settled();
    expect(sent).toEqual([]);

    reporter.observeAccepted(9, failure);
    await reporter.settled();
    expect(sent).toEqual([{ kind: "turn_failed", agent_active: false }]);
  });

  it("reports a Pi runtime error at once when the stream dropped the event", async () => {
    const { reporter, sent } = createReporter();

    reporter.observe(
      piEvent({ type: "turn_completed", stopReason: "error" }),
      false,
    );
    await reporter.settled();

    expect(sent).toEqual([{ kind: "turn_failed", agent_active: false }]);
  });

  it("sends one heartbeat per 30 seconds of activity", async () => {
    const { reporter, sent, clock } = createReporter();

    reporter.observe(sessionUpdate("plan"), true);
    clock.nowMs = 29_999;
    reporter.observe(sessionUpdate("plan"), true);
    clock.nowMs = 30_000;
    reporter.observe(sessionUpdate("plan"), true);
    await reporter.settled();

    expect(sent).toEqual([
      { kind: "heartbeat", agent_active: true, activity_started: true },
      { kind: "heartbeat", agent_active: true, activity_started: false },
    ]);
  });

  it("stays quiet after a turn ends until the agent is active again", async () => {
    const { reporter, sent } = createReporter();

    reporter.observe(sessionUpdate("plan"), true);
    reporter.observe(turnComplete("end_turn"), true);
    reporter.observe(
      {
        type: "notification",
        notification: { method: "_posthog/usage" },
      },
      true,
    );
    reporter.observe(sessionUpdate("plan"), true);
    await reporter.settled();

    expect(sent.map((callback) => callback.kind)).toEqual([
      "heartbeat",
      "awaiting_input",
      "heartbeat",
    ]);
    expect(sent[2]).toMatchObject({ activity_started: true });
  });

  it.each([
    {
      kind: "command_dispatched",
      event: {
        type: "notification",
        notification: { method: "_posthog/agent_command_dispatched" },
      },
    },
    { kind: "agent_activity", event: sessionUpdate("agent_message_chunk") },
    {
      kind: "agent_activity",
      event: piEvent({ type: "assistant_message_chunk" }),
    },
  ])("reports the $kind boot milestone once", async ({ kind, event }) => {
    const { reporter, sent } = createReporter();

    reporter.observe(event, true);
    reporter.observe(event, true);
    await reporter.settled();

    expect(sent.filter((callback) => callback.kind === kind)).toHaveLength(1);
  });

  it.each([
    {
      name: "again after the server failed",
      first: () =>
        Promise.reject(Object.assign(new Error("down"), { status: 503 })),
      reports: 2,
    },
    {
      name: "again after Django skipped the dispatch",
      first: () => Promise.resolve(false),
      reports: 2,
    },
    {
      name: "once when the server refused it",
      first: () =>
        Promise.reject(Object.assign(new Error("forbidden"), { status: 403 })),
      reports: 1,
    },
  ])("reports a boot milestone $name", async ({ first, reports }) => {
    const send = vi
      .fn<(callback: AgentCallback) => Promise<boolean>>()
      .mockImplementationOnce(first)
      .mockResolvedValue(true);
    const { reporter, sent } = createReporter(send);
    const dispatched = {
      type: "notification",
      notification: { method: "_posthog/agent_command_dispatched" },
    };

    reporter.observe(dispatched, true);
    await reporter.settled();
    reporter.observe(dispatched, true);
    await reporter.settled();

    expect(sent).toHaveLength(reports);
  });

  it.each([
    {
      name: "retries a finished turn after a server error",
      event: turnComplete("end_turn"),
      failure: Object.assign(new Error("unavailable"), { status: 503 }),
      attempts: 2,
    },
    {
      name: "retries a finished turn after a network error",
      event: turnComplete("end_turn"),
      failure: new Error("socket hang up"),
      attempts: 2,
    },
    {
      name: "does not retry a finished turn the server refused",
      event: turnComplete("end_turn"),
      failure: Object.assign(new Error("forbidden"), { status: 403 }),
      attempts: 1,
    },
    {
      name: "does not retry a heartbeat",
      event: sessionUpdate("plan"),
      failure: Object.assign(new Error("unavailable"), { status: 503 }),
      attempts: 1,
    },
  ])("$name", async ({ event, failure, attempts }) => {
    const { reporter, sent } = createReporter(async () => {
      throw failure;
    });

    reporter.observe(event, true);
    await reporter.settled();

    expect(sent).toHaveLength(attempts);
  });

  it.each([
    {
      name: "a budget steer",
      event: {
        type: "notification",
        timestamp: "2026-01-01T00:00:06.000Z",
        notification: {
          method: "_posthog/budget_steer",
          params: {
            stage: "critical",
            mode: "publish",
            delivered: true,
            spent_usd: 7,
            cap_usd: 10,
            secret: "not-for-analytics",
          },
        },
      },
      expected: {
        kind: "budget_steer",
        agent_active: false,
        sequence: 7,
        timestamp: "2026-01-01T00:00:06.000Z",
        stage: "critical",
        mode: "publish",
        delivered: true,
        spent_usd: 7,
        cap_usd: 10,
      },
    },
    {
      name: "a process kill",
      event: {
        type: "notification",
        notification: {
          method: "_posthog/process_killed",
          params: {
            comm: "bash",
            signal: "SIGKILL",
            treeRssBytes: 100,
            memoryCurrentBytes: 200,
            memoryLimitBytes: 300,
            cmdline: "bash -c secret",
          },
        },
      },
      expected: {
        kind: "process_killed",
        agent_active: false,
        sequence: 7,
        process_killed: {
          comm: "bash",
          signal: "SIGKILL",
          tree_rss_bytes: 100,
          memory_current_bytes: 200,
          memory_limit_bytes: 300,
        },
      },
    },
  ])(
    "reports $name with its sequence and only the allowed fields",
    async ({ event, expected }) => {
      const { reporter, sent } = createReporter();

      reporter.observeAccepted(7, event);
      await reporter.settled();

      expect(JSON.parse(JSON.stringify(sent))).toEqual([expected]);
    },
  );

  it.each([
    {
      name: "the agent-proxy takes ingest and the token opts the agent in",
      claims: { agent_sends_callbacks: true },
      eventIngestBaseUrl: "http://agent-proxy:8003",
      reports: true,
    },
    {
      name: "the token does not opt the agent in",
      claims: { agent_sends_callbacks: false },
      eventIngestBaseUrl: "http://agent-proxy:8003",
      reports: false,
    },
    {
      name: "the token has no claim",
      claims: {},
      eventIngestBaseUrl: "http://agent-proxy:8003",
      reports: false,
    },
    {
      name: "Django takes ingest",
      claims: { agent_sends_callbacks: true },
      eventIngestBaseUrl: undefined,
      reports: false,
    },
  ])(
    "creates a reporter only when it should: $name",
    ({ claims, eventIngestBaseUrl, reports }) => {
      const reporter = createAgentCallbackReporter({
        eventIngestToken: ingestToken(claims),
        eventIngestBaseUrl,
        send: async () => true,
        logger: new Logger({ debug: false }),
      });

      expect(reporter !== null).toBe(reports);
    },
  );

  it("creates no reporter for a token it cannot read", () => {
    const reporter = createAgentCallbackReporter({
      eventIngestToken: "not-a-jwt",
      eventIngestBaseUrl: "http://agent-proxy:8003",
      send: async () => true,
      logger: new Logger({ debug: false }),
    });

    expect(reporter).toBeNull();
  });
});
