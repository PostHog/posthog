import type { AgentSession } from "@posthog/shared";
import type { TaskRun } from "@posthog/shared/domain-types";
import { describe, expect, it } from "vitest";
import {
  getCloudPrAuthorshipMode,
  getCloudRunSource,
  getCloudRuntimeOptions,
} from "./cloudRunOptions";

describe("getCloudPrAuthorshipMode", () => {
  it("honors an explicit user/bot mode", () => {
    expect(getCloudPrAuthorshipMode({ pr_authorship_mode: "bot" })).toBe("bot");
    expect(getCloudPrAuthorshipMode({ pr_authorship_mode: "user" })).toBe(
      "user",
    );
  });

  it("defaults signal_report runs to bot, everything else to user", () => {
    expect(getCloudPrAuthorshipMode({ run_source: "signal_report" })).toBe(
      "bot",
    );
    expect(getCloudPrAuthorshipMode({ run_source: "manual" })).toBe("user");
    expect(getCloudPrAuthorshipMode({})).toBe("user");
  });

  it("ignores an invalid explicit mode and falls back to run_source", () => {
    expect(
      getCloudPrAuthorshipMode({
        pr_authorship_mode: "nonsense",
        run_source: "signal_report",
      }),
    ).toBe("bot");
  });
});

describe("getCloudRunSource", () => {
  it("maps signal_report through and everything else to manual", () => {
    expect(getCloudRunSource({ run_source: "signal_report" })).toBe(
      "signal_report",
    );
    expect(getCloudRunSource({ run_source: "whatever" })).toBe("manual");
    expect(getCloudRunSource({})).toBe("manual");
  });
});

describe("getCloudRuntimeOptions", () => {
  const session = (overrides: Partial<AgentSession>): AgentSession =>
    ({ configOptions: [], ...overrides }) as unknown as AgentSession;

  it("prefers the session config option, then the previous run", () => {
    const result = getCloudRuntimeOptions(
      session({
        configOptions: [
          { category: "model", currentValue: "opus" },
          { category: "thought_level", currentValue: "high" },
          // biome-ignore lint/suspicious/noExplicitAny: minimal config option shape
        ] as any,
        adapter: undefined,
      }),
      {
        model: "sonnet",
        reasoning_effort: "low",
        runtime_adapter: "claude_code",
      } as unknown as TaskRun,
    );
    expect(result.model).toBe("opus");
    expect(result.reasoningLevel).toBe("high");
    expect(result.adapter).toBe("claude_code");
  });

  it("falls back to the previous run when the session has no config value", () => {
    const result = getCloudRuntimeOptions(session({ configOptions: [] }), {
      model: "sonnet",
      reasoning_effort: "low",
      runtime_adapter: "claude_code",
    } as unknown as TaskRun);
    expect(result.model).toBe("sonnet");
    expect(result.reasoningLevel).toBe("low");
    expect(result.adapter).toBe("claude_code");
  });

  it("returns undefined fields when neither source provides a value", () => {
    const result = getCloudRuntimeOptions(session({ configOptions: [] }));
    expect(result.model).toBeUndefined();
    expect(result.reasoningLevel).toBeUndefined();
    expect(result.adapter).toBeUndefined();
    expect(result.initialPermissionMode).toBeUndefined();
  });

  it.each([
    {
      label: "prefers the session mode config option for permission mode",
      configOptions: [
        { category: "mode", currentValue: "acceptEdits" },
        // biome-ignore lint/suspicious/noExplicitAny: minimal config option shape
      ] as any,
      previousRun: {
        state: { initial_permission_mode: "plan" },
      } as unknown as TaskRun,
      expected: "acceptEdits",
    },
    {
      label: "falls back to the previous run state for permission mode",
      configOptions: [],
      previousRun: {
        state: { initial_permission_mode: "acceptEdits" },
      } as unknown as TaskRun,
      expected: "acceptEdits",
    },
  ])("$label", ({ configOptions, previousRun, expected }) => {
    const result = getCloudRuntimeOptions(
      session({ configOptions }),
      previousRun,
    );
    expect(result.initialPermissionMode).toBe(expected);
  });
});
