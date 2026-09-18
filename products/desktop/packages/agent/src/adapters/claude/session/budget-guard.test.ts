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

function agentSpawn(toolName = "Agent"): HookInput {
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

  test("is disabled when the sandbox carries no cap", () => {
    expect(RunBudgetGuard.fromEnv({}, logger)).toBeNull();
    expect(
      RunBudgetGuard.fromEnv({ [BUDGET_CAP_ENV]: "0" }, logger),
    ).toBeNull();
    expect(
      RunBudgetGuard.fromEnv({ [BUDGET_CAP_ENV]: "abc" }, logger),
    ).toBeNull();
  });

  test("honours a price table override from the environment", () => {
    const guard = RunBudgetGuard.fromEnv(
      {
        [BUDGET_CAP_ENV]: "1",
        [BUDGET_PRICES_ENV]: JSON.stringify({
          opus: { input: 0, output: 0, cacheRead: 10, cacheWrite: 0 },
        }),
      },
      logger,
    );
    guard?.recordAssistantMessage(opusCall("m1", 50_000));
    expect(guard?.spentUsd).toBeCloseTo(0.5, 6);
  });

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

  test("snaps the estimate to the SDK's cumulative cost when a turn settles", () => {
    const guard = new RunBudgetGuard(10, DEFAULT_MODEL_PRICES, logger);
    guard.recordAssistantMessage(opusCall("m1", 1_000_000));
    expect(guard.spentUsd).toBeCloseTo(0.51126, 4);
    guard.calibrate(2.0);
    expect(guard.spentUsd).toBe(2.0);
    guard.recordAssistantMessage(opusCall("m2", 1_000_000));
    expect(guard.spentUsd).toBeCloseTo(2.51126, 4);
    guard.calibrate(1.0);
    expect(guard.spentUsd).toBeCloseTo(2.51126, 4);
    expect(guard.calibrate(8.6)).toMatchObject({ stage: "critical" });
    expect(guard.recordAssistantMessage(opusCall("m3", 1_000))).toBeNull();
    expect(guard.currentStage).toBe("critical");
  });

  test("denies subagent spawns only once the budget is critical", async () => {
    const guard = new RunBudgetGuard(1, DEFAULT_MODEL_PRICES, logger);
    const hook = guard.preToolUseHook();
    guard.recordAssistantMessage(opusCall("m1", 1_500_000));
    expect(guard.currentStage).toBe("warn");
    expect(
      await hook(agentSpawn(), undefined, {
        signal: new AbortController().signal,
      }),
    ).toEqual({
      continue: true,
    });
    guard.recordAssistantMessage(opusCall("m2", 500_000));
    expect(guard.currentStage).toBe("critical");
    const denied = await hook(agentSpawn(), undefined, {
      signal: new AbortController().signal,
    });
    expect(denied).toMatchObject({
      hookSpecificOutput: { permissionDecision: "deny" },
    });
    expect(
      await hook(agentSpawn("Bash"), undefined, {
        signal: new AbortController().signal,
      }),
    ).toEqual({ continue: true });
  });
});
