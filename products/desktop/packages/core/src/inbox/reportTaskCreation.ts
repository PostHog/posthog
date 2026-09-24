import {
  type Adapter,
  isRestrictedModelOption,
  pickAllowedModel,
  type TaskCreationInput,
} from "@posthog/shared";

/** A selectable choice, either flat or wrapped in a labelled group. */
export interface PreviewConfigChoice {
  value?: string;
  options?: PreviewConfigChoice[];
  _meta?: Record<string, unknown> | null;
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
 * Flatten the (possibly nested) choices into the selectable models, carrying
 * each one's plan entitlement. The gateway may return models either flat or
 * wrapped in labelled groups, so this mirrors `flattenConfigValues` in the
 * TaskInput picker — a model nested in a group must still count as available.
 */
function flattenModelChoices(
  choices: PreviewConfigChoice[],
): { id: string; allowed: boolean }[] {
  return choices.flatMap((choice) =>
    choice.options
      ? flattenModelChoices(choice.options)
      : choice.value
        ? [
            {
              id: choice.value,
              allowed: !isRestrictedModelOption(choice._meta ?? undefined),
            },
          ]
        : [],
  );
}

/**
 * Pick the model id out of the agent's preview-config options.
 *
 * Headless cloud flows (CONTEXT.md generation, freeform canvas, inbox
 * one-click) never draw a picker, so this is the only place a model the org's
 * plan doesn't cover can be caught before the run reaches the gateway.
 *
 * `preferredModel` (e.g. the user's persisted last-used model) is honoured only
 * if the gateway still offers it *and* the plan allows it: restricted models
 * stay in the option list on purpose so the picker can draw them locked, so
 * presence alone is not enough. Everything else resolves through
 * `pickAllowedModel`, which downgrades to the newest allowed model — the server
 * default (`currentValue`) can be restricted too. Without this the run dies on
 * a gateway 403 ("needs a paid PostHog plan") before any work happens.
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
  const models = flattenModelChoices(modelOption.options ?? []);
  if (
    preferredModel &&
    models.some((model) => model.id === preferredModel && model.allowed)
  ) {
    return preferredModel;
  }
  if (
    typeof modelOption.currentValue === "string" &&
    modelOption.currentValue
  ) {
    return pickAllowedModel(models, modelOption.currentValue);
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
