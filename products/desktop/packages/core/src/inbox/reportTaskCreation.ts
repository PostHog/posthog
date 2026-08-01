import type { Adapter, TaskCreationInput } from "@posthog/shared";

/** A selectable choice, either flat or wrapped in a labelled group. */
export interface PreviewConfigChoice {
  value?: string;
  options?: PreviewConfigChoice[];
}

/** Minimal shape of a preview-config option we scan for the default model. */
export interface PreviewConfigOption {
  id?: string;
  category?: string | null;
  type?: string;
  currentValue?: string | boolean | null;
  options?: PreviewConfigChoice[];
}

/**
 * Flatten the (possibly nested) choices into the set of selectable values.
 * The gateway may return models either flat or wrapped in labelled groups, so
 * this mirrors `flattenConfigValues` in the TaskInput picker — a model nested in
 * a group must still count as available.
 */
function flattenChoiceValues(choices: PreviewConfigChoice[]): string[] {
  return choices.flatMap((choice) =>
    choice.options
      ? flattenChoiceValues(choice.options)
      : choice.value
        ? [choice.value]
        : [],
  );
}

/**
 * Pick the model id out of the agent's preview-config options.
 *
 * When `preferredModel` is supplied (e.g. the user's persisted last-used model)
 * it is honoured only if it is still one of the gateway's available models;
 * otherwise we fall back to the server default (`currentValue`). One-click cloud
 * flows pass their persisted model here so a stale id the gateway no longer
 * offers can't slip through — without the check the run fails with a gateway 403
 * (e.g. a previously-selected model that was later de-listed for the org).
 */
export function selectModelFromOptions(
  options: PreviewConfigOption[],
  preferredModel?: string | null,
): string | undefined {
  const modelOption = options.find(
    (o) => o.id === "model" || o.category === "model",
  );
  if (modelOption?.type !== "select") {
    return undefined;
  }
  if (
    preferredModel &&
    modelOption.options &&
    flattenChoiceValues(modelOption.options).includes(preferredModel)
  ) {
    return preferredModel;
  }
  if (
    typeof modelOption.currentValue === "string" &&
    modelOption.currentValue
  ) {
    return modelOption.currentValue;
  }
  return undefined;
}

export interface BuildSignalReportTaskInput {
  prompt: string;
  reportId: string;
  cloudRepository: string;
  githubUserIntegrationId: string;
  adapter: Adapter;
  model: string;
  reasoningLevel?: string;
  baseBranch?: string | null;
}

/** Build the `TaskCreationInput` for an inbox direct-create (Discuss / Create-PR) flow. */
export function buildSignalReportTaskInput(
  args: BuildSignalReportTaskInput,
): TaskCreationInput {
  const {
    prompt,
    reportId,
    cloudRepository,
    githubUserIntegrationId,
    adapter,
    model,
    reasoningLevel,
    baseBranch,
  } = args;
  return {
    content: prompt,
    taskDescription: prompt,
    repository: cloudRepository,
    githubUserIntegrationId,
    workspaceMode: "cloud",
    executionMode: "auto",
    adapter,
    model,
    branch: baseBranch ?? null,
    reasoningLevel: reasoningLevel ?? undefined,
    cloudPrAuthorshipMode: "user",
    cloudRunSource: "signal_report",
    signalReportId: reportId,
  };
}
