import { describe, expect, it } from "vitest";
import { Logger } from "../utils/logger";
import {
  type AgentCallback,
  AgentCallbackReporter,
  createAgentCallbackReporter,
} from "./agent-callback-reporter";

const ingestToken = (claims: Record<string, unknown>): string =>
  `header.${Buffer.from(JSON.stringify(claims)).toString("base64url")}.signature`;

function createReporter(
  send: (callback: AgentCallback) => Promise<void> = async () => {},
) {
  const log: string[] = [];
  const sent: AgentCallback[] = [];
  const clock = { nowMs: 0 };
  const reporter = new AgentCallbackReporter({
    send: async (callback) => {
      log.push(callback.kind);
      sent.push(callback);
      await send(callback);
    },
    flushEvents: async () => {
      log.push("flush");
    },
    logger: new Logger({ debug: false }),
    now: () => clock.nowMs,
    retryDelayMs: 0,
  });
  return { reporter, sent, log, clock };
}

describe("AgentCallbackReporter", () => {
  it("sends one heartbeat per 30 seconds of activity", async () => {
    const { reporter, sent, clock } = createReporter();

    reporter.agentActivity();
    clock.nowMs = 29_999;
    reporter.agentActivity();
    clock.nowMs = 30_000;
    reporter.agentActivity();
    await reporter.settled();

    expect(sent).toEqual([
      { kind: "heartbeat", agent_active: true, activity_started: true },
      { kind: "heartbeat", agent_active: true, activity_started: false },
    ]);
  });

  it("heartbeats at once when activity resumes after a finished turn", async () => {
    const { reporter, sent } = createReporter();

    reporter.agentActivity();
    reporter.turnCompleted("end_turn");
    reporter.agentActivity();
    await reporter.settled();

    expect(sent.filter((callback) => callback.kind === "heartbeat")).toEqual([
      { kind: "heartbeat", agent_active: true, activity_started: true },
      { kind: "heartbeat", agent_active: true, activity_started: true },
    ]);
  });

  it.each([
    { stopReason: "end_turn", turn_completed: true, turn_succeeded: true },
    { stopReason: "cancelled", turn_completed: true, turn_succeeded: false },
    { stopReason: "idle_resume", turn_completed: false, turn_succeeded: false },
  ])(
    "reports a turn that stopped with $stopReason",
    async ({ stopReason, turn_completed, turn_succeeded }) => {
      const { reporter, sent } = createReporter();

      reporter.turnCompleted(stopReason);
      await reporter.settled();

      expect(sent).toEqual([
        {
          kind: "awaiting_input",
          agent_active: false,
          turn_completed,
          turn_succeeded,
        },
      ]);
    },
  );

  it("flushes the event stream before it reports a finished turn", async () => {
    const { reporter, log } = createReporter();

    reporter.turnCompleted("end_turn");
    await reporter.settled();

    expect(log).toEqual(["flush", "awaiting_input"]);
  });

  it.each([
    {
      name: "retries a finished turn after a server error",
      report: (reporter: AgentCallbackReporter) =>
        reporter.turnCompleted("end_turn"),
      failure: Object.assign(new Error("unavailable"), { status: 503 }),
      attempts: 2,
    },
    {
      name: "retries a finished turn after a network error",
      report: (reporter: AgentCallbackReporter) =>
        reporter.turnCompleted("end_turn"),
      failure: new Error("socket hang up"),
      attempts: 2,
    },
    {
      name: "does not retry a finished turn the server refused",
      report: (reporter: AgentCallbackReporter) =>
        reporter.turnCompleted("end_turn"),
      failure: Object.assign(new Error("forbidden"), { status: 403 }),
      attempts: 1,
    },
    {
      name: "does not retry a heartbeat",
      report: (reporter: AgentCallbackReporter) => reporter.agentActivity(),
      failure: Object.assign(new Error("unavailable"), { status: 503 }),
      attempts: 1,
    },
  ])("$name", async ({ report, failure, attempts }) => {
    const { reporter, sent } = createReporter(async () => {
      throw failure;
    });

    report(reporter);
    await reporter.settled();

    expect(sent).toHaveLength(attempts);
  });

  it.each([
    {
      name: "the agent-proxy takes ingest and the token opts the agent in",
      eventIngestToken: ingestToken({ agent_sends_callbacks: true }),
      eventIngestBaseUrl: "http://agent-proxy:8003",
      reports: true,
    },
    {
      name: "the token does not opt the agent in",
      eventIngestToken: ingestToken({ agent_sends_callbacks: false }),
      eventIngestBaseUrl: "http://agent-proxy:8003",
      reports: false,
    },
    {
      name: "the token has no claim",
      eventIngestToken: ingestToken({}),
      eventIngestBaseUrl: "http://agent-proxy:8003",
      reports: false,
    },
    {
      name: "the token cannot be read",
      eventIngestToken: "not-a-jwt",
      eventIngestBaseUrl: "http://agent-proxy:8003",
      reports: false,
    },
    {
      name: "Django takes ingest",
      eventIngestToken: ingestToken({ agent_sends_callbacks: true }),
      eventIngestBaseUrl: undefined,
      reports: false,
    },
  ])(
    "creates a reporter only when it should: $name",
    ({ eventIngestToken, eventIngestBaseUrl, reports }) => {
      const reporter = createAgentCallbackReporter({
        eventIngestToken,
        eventIngestBaseUrl,
        send: async () => {},
        flushEvents: async () => {},
        logger: new Logger({ debug: false }),
      });

      expect(reporter !== null).toBe(reports);
    },
  );
});
