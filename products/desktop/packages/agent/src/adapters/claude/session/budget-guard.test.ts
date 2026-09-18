import type { HookInput } from "@anthropic-ai/claude-agent-sdk";
import { describe, expect, test } from "vitest";
import { Logger } from "../../../utils/logger";
import {
  BUDGET_CAP_ENV,
  BUDGET_PRICES_ENV,
  DEFAULT_MODEL_PRICES,
  estimateMessageCostUsd,
  RunBudgetGuard,
} from "./budget-guard";

const logger = new Logger({ debug: false });

function opusCall(id: string, cacheReadTokens: number) {
  return {
    id,
    model: "claude-opus-5",
    usage: {
      input_tokens: 2,
      output_tokens: 200,
      cache_read_input_tokens: cacheReadTokens,
      cache_creation_input_tokens: 1_000,
    },
  };
}

function spawn(toolName: string): HookInput {
  return {
    session_id: "s",
    transcript_path: "/tmp/t",
    cwd: "/tmp",
    hook_event_name: "PreToolUse",
    tool_name: toolName,
    tool_input: {},
    tool_use_id: "toolu_1",
  } as HookInput;
}

const hookOptions = () => ({ signal: new AbortController().signal });

describe("RunBudgetGuard", () => {
  test("prices an opus call the way the gateway bills it", () => {
    const cost = estimateMessageCostUsd(
      opusCall("m1", 256_387),
      DEFAULT_MODEL_PRICES,
    );
    expect(cost).toBeCloseTo(0.1395, 3);
  });

  test("falls back to opus pricing for an unknown model", () => {
    const known = estimateMessageCostUsd(
      opusCall("m1", 100_000),
      DEFAULT_MODEL_PRICES,
    );
    const unknown = estimateMessageCostUsd(
      { ...opusCall("m1", 100_000), model: "claude-something-new" },
      DEFAULT_MODEL_PRICES,
    );
    expect(unknown).toBe(known);
  });

  test("charges one-hour cache writes at twice the input price and fast mode at six times", () => {
    const flat = estimateMessageCostUsd(
      {
        model: "claude-opus-5",
        usage: { cache_creation_input_tokens: 1_000_000 },
      },
      DEFAULT_MODEL_PRICES,
    );
    const oneHour = estimateMessageCostUsd(
      {
        model: "claude-opus-5",
        usage: {
          cache_creation_input_tokens: 1_000_000,
          cache_creation: { ephemeral_1h_input_tokens: 1_000_000 },
        },
      },
      DEFAULT_MODEL_PRICES,
    );
    const fast = estimateMessageCostUsd(
      {
        model: "claude-opus-5",
        usage: { output_tokens: 1_000_000, speed: "fast" },
      },
      DEFAULT_MODEL_PRICES,
    );
    expect(flat).toBeCloseTo(6.25, 6);
    expect(oneHour).toBeCloseTo(10, 6);
    expect(fast).toBeCloseTo(150, 6);
  });

  test("is disabled when the sandbox carries no cap", () => {
    expect(RunBudgetGuard.fromEnv({}, logger)).toBeNull();
    expect(
      RunBudgetGuard.fromEnv({ [BUDGET_CAP_ENV]: "0" }, logger),
    ).toBeNull();
    expect(
      RunBudgetGuard.fromEnv({ [BUDGET_CAP_ENV]: "abc" }, logger),
    ).toBeNull();
  });

  test.each([
    [
      '{"opus": {"input": 0, "output": 0, "cacheRead": 10, "cacheWrite": 0}}',
      0.5,
    ],
    [
      '{"opus": {"input": 0, "output": 0, "cacheRead": -10, "cacheWrite": 0}}',
      0.03626,
    ],
    [
      '{"opus": {"input": 0, "output": 0, "cacheRead": 1e400, "cacheWrite": 0}}',
      0.03626,
    ],
    ["not json", 0.03626],
  ])(
    "price override %s yields spend %s for a 50k cache read",
    (raw, expected) => {
      const guard = RunBudgetGuard.fromEnv(
        { [BUDGET_CAP_ENV]: "1", [BUDGET_PRICES_ENV]: raw },
        logger,
      );
      guard?.recordAssistantMessage(opusCall("m1", 50_000));
      expect(guard?.spentUsd).toBeCloseTo(expected, 4);
    },
  );

  test("fires warn once and critical once, in order, and dedupes repeated message ids", () => {
    const guard = new RunBudgetGuard(1, DEFAULT_MODEL_PRICES, logger);
    const events: string[] = [];
    const record = (id: string, cacheRead: number) => {
      const event = guard.recordAssistantMessage(opusCall(id, cacheRead));
      if (event) events.push(event.stage);
    };
    record("m1", 1_000_000);
    record("m1", 1_000_000);
    expect(guard.spentUsd).toBeCloseTo(0.51126, 4);
    expect(events).toEqual([]);
    record("m2", 500_000);
    expect(events).toEqual(["warn"]);
    record("m3", 100_000);
    record("m4", 200_000);
    expect(events).toEqual(["warn", "critical"]);
    record("m5", 1_000_000);
    expect(events).toEqual(["warn", "critical"]);
  });

  test("keeps a threshold pending until a steer is delivered, and critical supersedes warn", () => {
    const guard = new RunBudgetGuard(1, DEFAULT_MODEL_PRICES, logger);
    guard.recordAssistantMessage(opusCall("m1", 1_500_000));
    expect(guard.takePendingSteer()).toBe("warn");
    expect(guard.takePendingSteer()).toBeNull();
    guard.markUndelivered("warn");
    guard.recordAssistantMessage(opusCall("m2", 500_000));
    expect(guard.takePendingSteer()).toBe("critical");
    guard.markUndelivered("warn");
    guard.markUndelivered("critical");
    guard.markUndelivered("warn");
    expect(guard.takePendingSteer()).toBe("critical");
  });

  test("never lets the SDK total erase spend the estimate already counted", () => {
    const guard = new RunBudgetGuard(10, DEFAULT_MODEL_PRICES, logger);
    guard.recordAssistantMessage(opusCall("m1", 1_000_000));
    expect(guard.spentUsd).toBeCloseTo(0.51126, 4);
    guard.calibrate(2.0);
    expect(guard.spentUsd).toBe(2.0);
    guard.recordAssistantMessage(opusCall("m2", 1_000_000));
    expect(guard.spentUsd).toBeCloseTo(2.51126, 4);
    guard.calibrate(1.0);
    expect(guard.spentUsd).toBeCloseTo(3.0, 4);
    expect(guard.calibrate(8.6)).toMatchObject({ stage: "critical" });
    expect(guard.recordAssistantMessage(opusCall("m3", 1_000))).toBeNull();
    expect(guard.currentStage).toBe("critical");
  });

  test("carries spend across a query reset instead of restarting from the new query's total", () => {
    const guard = new RunBudgetGuard(10, DEFAULT_MODEL_PRICES, logger);
    guard.calibrate(4.0);
    guard.onQueryReset();
    guard.calibrate(0.5);
    expect(guard.spentUsd).toBeCloseTo(4.5, 6);
    guard.calibrate(0.9);
    expect(guard.spentUsd).toBeCloseTo(4.9, 6);
    guard.calibrate(0.2);
    expect(guard.spentUsd).toBeCloseTo(5.1, 6);
    expect(guard.snapshot().sdk_total_usd).toBeCloseTo(5.1, 6);
  });

  test.each(["Agent", "Task", "Workflow"])(
    "denies a %s spawn only once the budget is critical",
    async (toolName) => {
      const guard = new RunBudgetGuard(1, DEFAULT_MODEL_PRICES, logger);
      const hook = guard.preToolUseHook();
      guard.recordAssistantMessage(opusCall("m1", 1_500_000));
      expect(guard.currentStage).toBe("warn");
      expect(await hook(spawn(toolName), undefined, hookOptions())).toEqual({
        continue: true,
      });
      guard.recordAssistantMessage(opusCall("m2", 500_000));
      expect(guard.currentStage).toBe("critical");
      expect(
        await hook(spawn(toolName), undefined, hookOptions()),
      ).toMatchObject({
        hookSpecificOutput: { permissionDecision: "deny" },
      });
      expect(await hook(spawn("Bash"), undefined, hookOptions())).toEqual({
        continue: true,
      });
    },
  );

  test("only a publish-mode guard tells the agent to commit and open a pull request", () => {
    const publish = new RunBudgetGuard(
      1,
      DEFAULT_MODEL_PRICES,
      logger,
      "publish",
    );
    const wrapUp = new RunBudgetGuard(
      1,
      DEFAULT_MODEL_PRICES,
      logger,
      "wrap_up",
    );
    for (const stage of ["warn", "critical"] as const) {
      expect(publish.steerText(stage)).toContain("git_signed_commit");
      expect(publish.steerText(stage)).not.toMatch(/, push,/);
      expect(wrapUp.steerText(stage)).not.toContain("git_signed_commit");
      expect(wrapUp.steerText(stage)).not.toContain("pull request");
    }
  });

  test("snapshots the steers it recorded", () => {
    const guard = new RunBudgetGuard(
      1,
      DEFAULT_MODEL_PRICES,
      logger,
      "publish",
    );
    guard.recordAssistantMessage(opusCall("m1", 1_500_000));
    guard.recordSteer("warn", false);
    guard.recordSteer("warn", true);
    expect(guard.snapshot()).toMatchObject({
      cap_usd: 1,
      stage: "warn",
      mode: "publish",
      steers: [
        { stage: "warn", delivered: false },
        { stage: "warn", delivered: true },
      ],
    });
  });
});
