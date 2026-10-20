import { describe, expect, it, vi } from "vitest";
import { Logger } from "../utils/logger";
import {
  type AgentCallback,
  AgentCallbackReporter,
  createAgentCallbackReporter,
} from "./agent-callback-reporter";

const ingestToken = (claims: Record<string, unknown>): string =>
  `header.${Buffer.from(JSON.stringify(claims)).toString("base64url")}.signature`;

function createReporter({
  send = async () => true,
  awaitEventAck = async () => 7,
  ackTimeoutMs,
  sendsCallbacks = true,
}: {
  send?: (callback: AgentCallback) => Promise<boolean>;
  awaitEventAck?: () => Promise<number | null>;
  ackTimeoutMs?: number;
  sendsCallbacks?: boolean;
} = {}) {
  const sent: AgentCallback[] = [];
  const clock = { nowMs: 0 };
  const reporter = new AgentCallbackReporter({
    sendsCallbacks,
    send: async (callback) => {
      sent.push(callback);
      return send(callback);
    },
    awaitEventAck,
    logger: new Logger({ debug: false }),
    now: () => clock.nowMs,
    retryDelayMs: 0,
    ackTimeoutMs,
  });
  return { reporter, sent, clock };
}

describe("AgentCallbackReporter", () => {
  it("sends one heartbeat per 30 seconds of activity", async () => {
    const { reporter, sent, clock } = createReporter();

    reporter.agentActivity(false);
    clock.nowMs = 29_999;
    reporter.agentActivity(false);
    clock.nowMs = 30_000;
    reporter.agentActivity(false);
    await reporter.settled();

    expect(sent).toEqual([
      { kind: "heartbeat", agent_active: true, activity_started: true },
      { kind: "heartbeat", agent_active: true, activity_started: false },
    ]);
  });

  it("reports the first generating activity as a boot milestone once", async () => {
    const { reporter, sent } = createReporter();

    reporter.agentActivity(true);
    reporter.agentActivity(true);
    await reporter.settled();

    expect(
      sent.filter((callback) => callback.kind === "agent_activity"),
    ).toEqual([{ kind: "agent_activity", agent_active: true }]);
  });

  it.each([
    { stopReason: "end_turn", turn_completed: true, turn_succeeded: true },
    { stopReason: "cancelled", turn_completed: true, turn_succeeded: false },
    { stopReason: "idle_resume", turn_completed: false, turn_succeeded: false },
  ])(
    "reports a turn that stopped with $stopReason and the acked sequence",
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
          sequence: 7,
        },
      ]);
    },
  );

  it("reports a failed turn with the acked sequence", async () => {
    const { reporter, sent } = createReporter();

    reporter.turnFailed();
    await reporter.settled();

    expect(sent).toEqual([
      { kind: "turn_failed", agent_active: false, sequence: 7 },
    ]);
  });

  it("waits for the ack and keeps later callbacks behind it", async () => {
    let ack: (sequence: number) => void = () => {};
    const { reporter, sent } = createReporter({
      awaitEventAck: () =>
        new Promise<number>((resolve) => {
          ack = resolve;
        }),
    });

    reporter.turnCompleted("end_turn");
    reporter.agentActivity(false);
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(sent).toEqual([]);

    ack(12);
    await reporter.settled();

    expect(sent.map((callback) => callback.kind)).toEqual([
      "awaiting_input",
      "heartbeat",
    ]);
    expect(sent[0]).toMatchObject({ sequence: 12 });
  });

  it.each([
    {
      name: "reports a finished turn without a sequence",
      report: (reporter: AgentCallbackReporter) =>
        reporter.turnCompleted("end_turn"),
      expected: [
        {
          kind: "awaiting_input",
          agent_active: false,
          turn_completed: true,
          turn_succeeded: true,
        },
      ],
    },
    {
      name: "drops a budget steer",
      report: (reporter: AgentCallbackReporter) =>
        reporter.budgetSteer({ stage: "warn" }),
      expected: [],
    },
  ])("$name when the ack never comes", async ({ report, expected }) => {
    const { reporter, sent } = createReporter({
      awaitEventAck: () => new Promise<number>(() => {}),
      ackTimeoutMs: 1,
    });

    report(reporter);
    await reporter.settled();

    expect(sent).toEqual(expected);
  });

  it.each([
    {
      name: "a budget steer",
      report: (reporter: AgentCallbackReporter) =>
        reporter.budgetSteer({
          stage: "critical",
          mode: "publish",
          delivered: true,
          spent_usd: 7,
          cap_usd: 10,
          secret: "not-for-analytics",
        }),
      expected: {
        kind: "budget_steer",
        agent_active: false,
        sequence: 7,
        timestamp: "1970-01-01T00:00:00.000Z",
        stage: "critical",
        mode: "publish",
        delivered: true,
        spent_usd: 7,
        cap_usd: 10,
      },
    },
    {
      name: "a process kill",
      report: (reporter: AgentCallbackReporter) =>
        reporter.processKilled({
          pid: 1,
          comm: "bash",
          signal: "SIGKILL",
          treeRssBytes: 100,
          memoryCurrentBytes: 200,
          memoryLimitBytes: 300,
          at: "2026-01-01T00:00:00.000Z",
        }),
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
    "reports $name with the acked sequence and only the allowed fields",
    async ({ report, expected }) => {
      const { reporter, sent } = createReporter();

      report(reporter);
      await reporter.settled();

      expect(JSON.parse(JSON.stringify(sent))).toEqual([expected]);
    },
  );

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
  ])("reports the command boot milestone $name", async ({ first, reports }) => {
    const send = vi
      .fn<(callback: AgentCallback) => Promise<boolean>>()
      .mockImplementationOnce(first)
      .mockResolvedValue(true);
    const { reporter, sent } = createReporter({ send });

    reporter.commandDispatched();
    await reporter.settled();
    reporter.commandDispatched();
    await reporter.settled();

    expect(sent).toHaveLength(reports);
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
      report: (reporter: AgentCallbackReporter) =>
        reporter.agentActivity(false),
      failure: Object.assign(new Error("unavailable"), { status: 503 }),
      attempts: 1,
    },
  ])("$name", async ({ report, failure, attempts }) => {
    const { reporter, sent } = createReporter({
      send: async () => {
        throw failure;
      },
    });

    report(reporter);
    await reporter.settled();

    expect(sent).toHaveLength(attempts);
  });

  it.each([
    {
      name: "the token opts the agent in",
      eventIngestToken: ingestToken({ agent_sends_callbacks: true }),
      reports: true,
    },
    {
      name: "the token does not opt the agent in",
      eventIngestToken: ingestToken({ agent_sends_callbacks: false }),
      reports: false,
    },
    {
      name: "the token has no claim",
      eventIngestToken: ingestToken({}),
      reports: false,
    },
    {
      name: "the token cannot be read",
      eventIngestToken: "not-a-jwt",
      reports: false,
    },
    {
      name: "there is no token",
      eventIngestToken: undefined,
      reports: false,
    },
  ])(
    "sends turn callbacks only when $name",
    ({ eventIngestToken, reports }) => {
      const reporter = createAgentCallbackReporter({
        eventIngestToken,
        send: async () => true,
        awaitEventAck: async () => null,
        logger: new Logger({ debug: false }),
      });

      expect(reporter.sendsCallbacks).toBe(reports);
    },
  );

  it("reports run events without the callbacks opt-in", async () => {
    const { reporter, sent } = createReporter({ sendsCallbacks: false });

    reporter.turnCompleted("end_turn");
    await reporter.reportRun({ type: "started", agent_version: "1.0.0" });

    expect(sent).toEqual([
      {
        kind: "run_event",
        agent_active: false,
        event: { type: "started", agent_version: "1.0.0" },
      },
    ]);
  });

  it("drops run events after the run failed", async () => {
    const { reporter, sent } = createReporter({ sendsCallbacks: false });

    await reporter.reportRun({
      type: "failed",
      error_type: "agent_reported",
      cause: "boom",
    });
    const outcome = await reporter.reportRun({
      type: "usage",
      token_usage: { turns: 1 },
    });

    expect([sent.length, outcome]).toEqual([1, "skipped"]);
  });

  it("does not hold run events behind a callback waiting for its ack", async () => {
    const { reporter, sent } = createReporter({
      awaitEventAck: () => new Promise<number>(() => {}),
    });

    reporter.turnCompleted("end_turn");
    await reporter.reportRun({ type: "started", agent_version: "1.0.0" });

    expect(sent.map((callback) => callback.kind)).toEqual(["run_event"]);
  });

  it("stops reporting once the server says the run has ended", async () => {
    const { reporter, sent } = createReporter({
      sendsCallbacks: false,
      send: async () => {
        throw Object.assign(new Error("conflict"), { status: 409 });
      },
    });

    const refused = await reporter.reportRun({
      type: "branch_changed",
      branch: "feat/x",
    });
    const dropped = await reporter.reportRun({
      type: "pr_detected",
      pr_url: "https://github.com/org/repo/pull/1",
    });

    expect([refused, dropped, sent.length]).toEqual(["refused", "skipped", 1]);
  });
  it("reports at once without a sequence after it stops waiting for acks", async () => {
    const { reporter, sent } = createReporter({
      awaitEventAck: () => new Promise<number>(() => {}),
    });

    reporter.turnCompleted("end_turn");
    reporter.stopWaitingForAcks();
    await reporter.settled();

    expect(sent).toEqual([
      {
        kind: "awaiting_input",
        agent_active: false,
        turn_completed: true,
        turn_succeeded: true,
      },
    ]);
  });
});
