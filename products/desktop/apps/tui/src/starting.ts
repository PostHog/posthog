import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import {
  DEFAULT_MODEL_BY_RUNTIME_ADAPTER,
  isOfferedModel,
  MODELS,
} from "@posthog/shared/model-catalog";
import type { Billing } from "./billing";
import { CHATGPT_MODEL } from "./chatgpt";
import {
  EFFORT_LABELS,
  type Effort,
  type ModelChoice,
  STARTING_MODEL,
  shortModelName,
} from "./models";

// What a chat can start on before its agent runs: the models its agent offers, and the pick it starts with.
export interface StartingOptions {
  models: ModelChoice[];
  model: ModelChoice | null;
  effort: Effort | null;
  efforts(model: ModelChoice): Effort[];
}

export interface ClaudeSettings {
  model?: string;
  effortLevel?: string;
}

const asEffort = (value: string | undefined): Effort | null =>
  value && value in EFFORT_LABELS ? (value as Effort) : null;

const choice = (provider: string, id: string): ModelChoice => ({
  provider,
  id,
  name: shortModelName(id),
});

const efforts = (model: ModelChoice): Effort[] =>
  (MODELS.find((entry) => entry.id === model.id)?.reasoningEfforts ?? [])
    .map(asEffort)
    .filter((effort): effort is Effort => effort !== null);

export function startingOptions(
  billing: Billing,
  place: "local" | "cloud",
  claude: ClaudeSettings = claudeSettings(),
): StartingOptions {
  if (billing === "posthog") {
    const models = MODELS.filter((entry) => isOfferedModel(entry.id)).map(
      (entry) => choice("posthog", entry.id),
    );
    return { models, model: STARTING_MODEL, effort: null, efforts };
  }
  const adapter = billing === "anthropic" ? "claude" : "codex";
  // The gateway serves other vendors through the Claude adapter; a Claude plan only runs Anthropic's own.
  const models = MODELS.filter(
    (entry) =>
      entry.runtimeAdapter === adapter &&
      isOfferedModel(entry.id) &&
      (adapter !== "claude" || entry.id.startsWith("claude-")),
  ).map((entry) => choice(adapter, entry.id));
  const wanted =
    adapter === "claude"
      ? claude.model
      : place === "local"
        ? CHATGPT_MODEL.split("/")[1]
        : undefined;
  const model =
    models.find((entry) => entry.id === wanted) ??
    models.find(
      (entry) => entry.id === DEFAULT_MODEL_BY_RUNTIME_ADAPTER[adapter],
    ) ??
    models[0] ??
    null;
  return {
    models,
    model,
    effort: adapter === "claude" ? asEffort(claude.effortLevel) : null,
    efforts,
  };
}

// The model and effort the user's own Claude Code starts on, from its settings file.
export function claudeSettings(): ClaudeSettings {
  try {
    return JSON.parse(
      readFileSync(join(homedir(), ".claude", "settings.json"), "utf8"),
    ) as ClaudeSettings;
  } catch {
    return {};
  }
}

export interface HeldPick {
  model?: ModelChoice;
  effort?: Effort;
}

// A pick held on a pane counts only while the chat it starts can run it; a /billing change drops the rest.
export function heldPick(held: HeldPick, starting: StartingOptions): HeldPick {
  const model = starting.models.find(
    (entry) =>
      entry.provider === held.model?.provider && entry.id === held.model.id,
  );
  const on = model ?? starting.model;
  const effort =
    held.effort && on && starting.efforts(on).includes(held.effort)
      ? held.effort
      : undefined;
  return { ...(model && { model }), ...(effort && { effort }) };
}
