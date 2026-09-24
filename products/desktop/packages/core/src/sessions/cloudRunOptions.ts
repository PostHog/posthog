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
import { harnessForModelValue } from "../task-detail/configOptions";

/**
 * Pure derivations of a cloud run's options from the host run state / session
 * config. Extracted from the renderer SessionService so the keystone keeps only
 * the I/O and these decisions are testable in isolation (Tiger-Style: the leaf
 * computes, the service applies).
 */

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
