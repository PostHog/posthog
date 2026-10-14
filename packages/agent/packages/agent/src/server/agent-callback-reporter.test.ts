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
  send: (callback: AgentCallback) => Promise<void> = async () => {},
) {
  const sent: AgentCallback[] = [];
  const clock = { nowMs: 0 };
  const reporter = new AgentCallbackReporter({
    send: async (callback) => {
      sent.push(callback);
      await send(callback);
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
    {
      name: "a Pi runtime error",
      event: piEvent({ type: "turn_completed", stopReason: "error" }),
      expected: { kind: "turn_failed", agent_active: false },
    },
  ])("reports $name", async ({ event, expected }) => {
    const { reporter, sent } = createReporter();

    reporter.observe(1, event);
    await reporter.settled();

    expect(sent).toEqual([expected]);
  });

  it("sends one heartbeat per 30 seconds of activity", async () => {
    const { reporter, sent, clock } = createReporter();

    reporter.observe(1, sessionUpdate("plan"));
    clock.nowMs = 29_999;
    reporter.observe(2, sessionUpdate("plan"));
    clock.nowMs = 30_000;
    reporter.observe(3, sessionUpdate("plan"));
    await reporter.settled();

    expect(sent).toEqual([
      { kind: "heartbeat", agent_active: true, activity_started: true },
      { kind: "heartbeat", agent_active: true, activity_started: false },
    ]);
  });

  it("stays quiet after a turn ends until the agent is active again", async () => {
    const { reporter, sent } = createReporter();

    reporter.observe(1, sessionUpdate("plan"));
    reporter.observe(2, turnComplete("end_turn"));
    reporter.observe(3, {
      type: "notification",
      notification: { method: "_posthog/usage" },
    });
    reporter.observe(4, sessionUpdate("plan"));
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

    reporter.observe(1, event);
    reporter.observe(2, event);
    await reporter.settled();

    expect(sent.filter((callback) => callback.kind === kind)).toHaveLength(1);
  });

  it("reports a boot milestone again after its callback failed", async () => {
    const send = vi
      .fn<(callback: AgentCallback) => Promise<void>>()
      .mockRejectedValueOnce(Object.assign(new Error("down"), { status: 503 }))
      .mockResolvedValue(undefined);
    const { reporter, sent } = createReporter(send);
    const dispatched = {
      type: "notification",
      notification: { method: "_posthog/agent_command_dispatched" },
    };

    reporter.observe(1, dispatched);
    await reporter.settled();
    reporter.observe(2, dispatched);
    await reporter.settled();

    expect(sent.map((callback) => callback.kind)).toEqual([
      "command_dispatched",
      "command_dispatched",
    ]);
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

    reporter.observe(1, event);
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

      reporter.observe(7, event);
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
        send: async () => {},
        logger: new Logger({ debug: false }),
      });

      expect(reporter !== undefined).toBe(reports);
    },
  );

  it("creates no reporter for a token it cannot read", () => {
    const reporter = createAgentCallbackReporter({
      eventIngestToken: "not-a-jwt",
      eventIngestBaseUrl: "http://agent-proxy:8003",
      send: async () => {},
      logger: new Logger({ debug: false }),
    });

    expect(reporter).toBeUndefined();
  });
});
