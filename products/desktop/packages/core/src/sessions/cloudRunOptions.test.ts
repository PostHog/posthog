import type { AgentSession } from "@posthog/shared";
import type { TaskRun } from "@posthog/shared/domain-types";
import { describe, expect, it } from "vitest";
import { cloudAccessFor, cloudModelAccessFromState } from "./cloudModelAccess";
import {
  getCloudPrAuthorshipMode,
  getCloudRunSource,
  getCloudRuntimeOptions,
  resolveCloudResumeOptions,
  sendConfiguredCloudPrompt,
} from "./cloudRunOptions";

describe("getCloudPrAuthorshipMode", () => {
  it.each([
    [{}, "posthog-gateway", "posthog-gateway"],
    [
      { claude_model_access: "own-subscription" },
      "own-subscription",
      "posthog-gateway",
    ],
    [
      { runtime_adapter: "codex", codex_model_access: "own-subscription" },
      "posthog-gateway",
      "own-subscription",
    ],
  ])("decodes legacy model access %s", (state, claude, codex) => {
    const access = cloudModelAccessFromState(state);
    expect(cloudAccessFor(access, "claude")).toBe(claude);
    expect(cloudAccessFor(access, "codex")).toBe(codex);
  });

  it.each([
    {
      claude_model_access: "own-subscription",
      codex_model_access: "own-subscription",
    },
    { runtime_adapter: "claude", codex_model_access: "own-subscription" },
  ])("rejects incompatible model access %s", (state) => {
    expect(() => cloudModelAccessFromState(state)).toThrow();
  });

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

  it.each([
    [true, "completed", "codex"],
    [true, "in_progress", "claude"],
    [false, undefined, "claude"],
  ] as const)(
    "selects the next runtime only for a completed cloud run (%s, %s)",
    (isCloud, cloudStatus, adapter) => {
      const result = getCloudRuntimeOptions(
        session({
          isCloud,
          cloudStatus,
          adapter: "claude",
          configOptions: [
            {
              id: "model",
              name: "Model",
              type: "select",
              category: "model",
              currentValue: "gpt-5.6-sol",
              options: [{ value: "gpt-5.6-sol", name: "GPT-5.6 Sol" }],
            },
          ],
        }),
        {
          runtime_adapter: "claude",
          reasoning_effort: "max",
          state: { initial_permission_mode: "acceptEdits" },
        } as unknown as TaskRun,
      );
      expect(result.adapter).toBe(adapter);
      if (adapter === "codex") {
        expect(result.reasoningLevel).toBeUndefined();
        expect(result.initialPermissionMode).toBeUndefined();
      }
    },
  );

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

describe("resolveCloudResumeOptions", () => {
  it("ignores legacy Claude composer values when resuming Codex", () => {
    expect(
      resolveCloudResumeOptions(
        { model: "claude-opus-4-8", reasoning: "high", mode: "plan" },
        {
          runtime_adapter: "codex",
          model: "gpt-5.5",
          reasoning_effort: "medium",
          state: { initial_permission_mode: "auto" },
        } as unknown as TaskRun,
      ),
    ).toEqual({
      adapter: "codex",
      model: "gpt-5.5",
      reasoningLevel: "medium",
      initialPermissionMode: "auto",
    });
  });

  it("does not carry previous run options across an explicit adapter change", () => {
    expect(
      resolveCloudResumeOptions(
        { adapter: "codex", model: "gpt-5.5", reasoning: "high", mode: "auto" },
        {
          model: "claude-opus-4-8",
          state: { initial_permission_mode: "plan" },
        } as unknown as TaskRun,
      ),
    ).toEqual({
      adapter: "codex",
      model: "gpt-5.5",
      reasoningLevel: "high",
      initialPermissionMode: "auto",
    });
  });
});

describe("sendConfiguredCloudPrompt", () => {
  it.each(["acp", "pi"] as const)(
    "sends with the selected model and effort on %s",
    async (runtime) => {
      const agent = { model: "old-model", effort: "low" };
      const messages: Array<typeof agent & { content: unknown }> = [];
      await sendConfiguredCloudPrompt(
        async (method, params) => {
          if (method === "user_message") {
            messages.push({ ...agent, content: params.content });
            return {};
          }
          if (method === "pi/rpc") {
            const command = params.command as {
              type: string;
              modelId?: string;
              level?: string;
            };
            if (command.type === "set_model")
              agent.model = String(command.modelId);
            else agent.effort = String(command.level);
            return { success: true };
          }
          if (params.configId === "model") agent.model = String(params.value);
          else agent.effort = String(params.value);
          return {
            configOptions: Object.entries(agent).map(([id, currentValue]) => ({
              id,
              currentValue,
            })),
          };
        },
        { model: "selected-model", reasoningLevel: "high" },
        "Continue",
        runtime,
      );
      expect(messages).toEqual([
        { content: "Continue", model: "selected-model", effort: "high" },
      ]);
    },
  );

  it.each(["model", "effort"])(
    "keeps the message unsent when %s is not accepted",
    async (rejected) => {
      const messages: unknown[] = [];
      await expect(
        sendConfiguredCloudPrompt(
          async (method, params) => {
            if (method === "user_message") {
              messages.push(params.content);
              return {};
            }
            return {
              configOptions: [
                {
                  id: params.configId,
                  currentValue:
                    params.configId === rejected ? "old-value" : params.value,
                },
              ],
            };
          },
          { model: "selected-model", reasoningLevel: "high" },
          "Continue",
        ),
      ).rejects.toThrow("did not accept");
      expect(messages).toEqual([]);
    },
  );

  it("keeps a Pi message unsent after a rejected model change", async () => {
    const messages: unknown[] = [];
    await expect(
      sendConfiguredCloudPrompt(
        async (method, params) => {
          if (method === "user_message") messages.push(params.content);
          return { success: false, error: "Unavailable model" };
        },
        { model: "selected-model" },
        "Continue",
        "pi",
      ),
    ).rejects.toThrow("did not accept");
    expect(messages).toEqual([]);
  });
});
