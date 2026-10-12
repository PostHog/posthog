import {
  type Adapter,
  type AgentSession,
  type CloudRunSource,
  type ExecutionMode,
  getConfigOptionByCategory,
  isSupportedReasoningEffort,
  isTerminalStatus,
  type PrAuthorshipMode,
  type SupportedReasoningEffort,
} from "@posthog/shared";
import type { TaskRun } from "@posthog/shared/domain-types";
import { z } from "zod";
import { harnessForModelValue } from "../task-detail/configOptions";

export function getCloudPrAuthorshipMode(
  state: Record<string, unknown>,
): PrAuthorshipMode {
  const explicitMode = state.pr_authorship_mode;
  if (explicitMode === "user" || explicitMode === "bot") {
    return explicitMode;
  }
  return state.run_source === "signal_report" ? "bot" : "user";
}

export function getCloudRunSource(
  state: Record<string, unknown>,
): CloudRunSource {
  return state.run_source === "signal_report" ? "signal_report" : "manual";
}

export interface CloudRuntimeOptions {
  adapter?: Adapter;
  model?: string;
  reasoningLevel?: string;
  initialPermissionMode?: ExecutionMode;
}

const configResultSchema = z.object({
  configOptions: z.array(
    z.object({ id: z.string(), currentValue: z.string() }),
  ),
});

export async function sendConfiguredCloudPrompt(
  command: (
    method: "set_config_option" | "user_message" | "pi/rpc",
    params: Record<string, unknown>,
  ) => Promise<unknown>,
  config: Pick<CloudRuntimeOptions, "model" | "reasoningLevel">,
  prompt: string,
  runtime: "acp" | "pi" = "acp",
): Promise<void> {
  for (const [configId, value] of [
    ["model", config.model],
    ["effort", config.reasoningLevel],
  ]) {
    if (!value) continue;
    if (runtime === "pi") {
      const result = z.object({ success: z.literal(true) }).safeParse(
        await command("pi/rpc", {
          command:
            configId === "model"
              ? { type: "set_model", provider: "posthog", modelId: value }
              : { type: "set_thinking_level", level: value },
        }),
      );
      if (!result.success)
        throw new Error(
          "The agent did not accept this setting. Choose it again before sending.",
        );
      continue;
    }
    const result = configResultSchema.safeParse(
      await command("set_config_option", { configId, value }),
    );
    if (
      !result.success ||
      !result.data.configOptions.some(
        (option) => option.id === configId && option.currentValue === value,
      )
    ) {
      throw new Error(
        "The agent did not accept this setting. Choose it again before sending.",
      );
    }
  }
  await command("user_message", { content: prompt });
}

export interface StoredCloudComposerConfig {
  adapter?: Adapter;
  model?: string;
  reasoning?: SupportedReasoningEffort;
  mode?: ExecutionMode;
}

export function resolveCloudResumeOptions(
  composerConfig: StoredCloudComposerConfig | undefined,
  previousRun: TaskRun | undefined,
): Required<Pick<CloudRuntimeOptions, "adapter">> &
  Omit<CloudRuntimeOptions, "adapter"> {
  const adapter =
    composerConfig?.adapter ?? previousRun?.runtime_adapter ?? "claude";
  const composerAdapter = composerConfig?.adapter ?? "claude";
  const useComposerConfig =
    composerConfig !== undefined && composerAdapter === adapter;
  const previousAdapter = previousRun?.runtime_adapter ?? "claude";
  const previousRunMatchesAdapter =
    previousRun !== undefined && previousAdapter === adapter;
  const model =
    (useComposerConfig ? composerConfig.model : undefined) ??
    (previousRunMatchesAdapter ? previousRun?.model : undefined) ??
    undefined;
  const requestedReasoning =
    (useComposerConfig ? composerConfig.reasoning : undefined) ??
    (previousRunMatchesAdapter ? previousRun?.reasoning_effort : undefined) ??
    undefined;
  const previousMode = previousRun?.state?.initial_permission_mode;

  return {
    adapter,
    model,
    reasoningLevel:
      model &&
      requestedReasoning &&
      isSupportedReasoningEffort(adapter, model, requestedReasoning)
        ? requestedReasoning
        : undefined,
    initialPermissionMode:
      (useComposerConfig ? composerConfig.mode : undefined) ??
      (previousRunMatchesAdapter && typeof previousMode === "string"
        ? (previousMode as ExecutionMode)
        : undefined),
  };
}

export function getCloudRuntimeOptions(
  session: AgentSession,
  previousRun?: TaskRun,
): CloudRuntimeOptions {
  const modelOption = getConfigOptionByCategory(session.configOptions, "model");
  const thoughtLevelOption = getConfigOptionByCategory(
    session.configOptions,
    "thought_level",
  );
  const modeOption = getConfigOptionByCategory(session.configOptions, "mode");
  const previousMode = previousRun?.state?.initial_permission_mode;
  const model =
    typeof modelOption?.currentValue === "string"
      ? modelOption.currentValue
      : (previousRun?.model ?? undefined);
  const isResume = session.isCloud && isTerminalStatus(session.cloudStatus);
  const adapter =
    (isResume && model
      ? harnessForModelValue(modelOption, model)
      : undefined) ??
    session.adapter ??
    previousRun?.runtime_adapter ??
    undefined;
  const adapterChanged =
    adapter !== (session.adapter ?? previousRun?.runtime_adapter);
  const reasoningLevel =
    typeof thoughtLevelOption?.currentValue === "string"
      ? thoughtLevelOption.currentValue
      : adapterChanged
        ? undefined
        : (previousRun?.reasoning_effort ?? undefined);
  return {
    adapter,
    model,
    reasoningLevel:
      isResume &&
      adapter &&
      model &&
      reasoningLevel &&
      !isSupportedReasoningEffort(adapter, model, reasoningLevel)
        ? undefined
        : reasoningLevel,
    initialPermissionMode:
      typeof modeOption?.currentValue === "string"
        ? (modeOption.currentValue as ExecutionMode)
        : !adapterChanged && typeof previousMode === "string"
          ? (previousMode as ExecutionMode)
          : undefined,
  };
}
