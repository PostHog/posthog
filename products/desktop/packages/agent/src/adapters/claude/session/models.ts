import {
  DEFAULT_OPTION_META_KEY,
  OPTION_DOCS_URL_META_KEY,
} from "@posthog/shared";
import {
  EFFORT_LEVEL_DOCS_URLS,
  EFFORT_LEVEL_LABELS,
} from "@posthog/shared/domain-types";
import {
  normalizeModelId,
  reasoningEffortsForModel,
} from "@posthog/shared/model-catalog";
import type { EffortLevel } from "../types";

export const DEFAULT_MODEL = "opus";

// Refusal/overload rescue target. The SDK rejects fallbackModel === Options.model
// at spawn, so this must stay distinct from the alias form used for DEFAULT_MODEL.
export const FALLBACK_MODEL = "claude-opus-4-8";

// Default thinking level when the user hasn't picked one. Adaptive-only models
// like claude-fable-5 reject the SDK's no-effort `thinking: { type: "disabled" }`
// shape, so effort-capable models default to high to keep thinking enabled.
export const DEFAULT_EFFORT: EffortLevel = "high";

export function resolveFallbackModel(modelId: string): string | undefined {
  return modelId === FALLBACK_MODEL ? undefined : FALLBACK_MODEL;
}

export function rerootedModelOptions(
  modelId: string | undefined,
  existingFallbackModel?: string,
  machineAuth?: boolean,
):
  | { model: string; fallbackModel: string | undefined }
  | Record<string, never> {
  if (!modelId) return {};
  if (machineAuth) {
    return { model: modelId, fallbackModel: undefined };
  }
  const fallbackModel =
    existingFallbackModel && existingFallbackModel !== modelId
      ? existingFallbackModel
      : resolveFallbackModel(modelId);
  return { model: modelId, fallbackModel };
}

const MODELS_WITH_1M_CONTEXT = new Set([
  "claude-opus-4-7",
  "claude-opus-4-8",
  "claude-opus-5",
  "claude-sonnet-4-6",
  "claude-sonnet-5",
  "claude-fable-5",
  "claude-fable-5-1",
]);

// Normalized like the effort lookup below: the gateway serves some ids
// provider-qualified, and a raw check there would silently drop the model to 200k.
export function supports1MContext(modelId: string): boolean {
  return MODELS_WITH_1M_CONTEXT.has(normalizeModelId(modelId));
}

export const CONTEXT_WINDOW_1M_BETA = "context-1m-2025-08-07";
export const CONTEXT_WINDOW_200K_TOKENS = 200_000;

interface ContextWindowOption {
  value: string;
  name: string;
  _meta?: Record<string, unknown>;
}

export function getContextWindowOptions(
  modelId: string,
): ContextWindowOption[] | null {
  if (!supports1MContext(modelId)) return null;
  return [
    { value: "200k", name: "200k" },
    { value: "1m", name: "1M", _meta: { [DEFAULT_OPTION_META_KEY]: true } },
  ];
}

function effortLevelsFor(modelId: string): readonly EffortLevel[] {
  return reasoningEffortsForModel("claude", modelId);
}

export function supportsEffort(modelId: string): boolean {
  return effortLevelsFor(modelId).length > 0;
}

export function resolveEffortForModel(
  modelId: string,
  effort: EffortLevel | undefined,
): EffortLevel | undefined {
  if (effort) return effort;
  return supportsEffort(modelId) ? DEFAULT_EFFORT : undefined;
}

export function supportsXhighEffort(modelId: string): boolean {
  return effortLevelsFor(modelId).includes("xhigh");
}

const MODELS_TO_EXCLUDE_MCP_TOOLS = new Set(["claude-haiku-4-5"]);

export function supportsMcpInjection(modelId: string): boolean {
  return !MODELS_TO_EXCLUDE_MCP_TOOLS.has(modelId);
}

const MODELS_WITH_FAST_MODE = new Set([
  "claude-opus-4-7",
  "claude-opus-4-8",
  "claude-opus-5",
]);

export function supportsFastMode(modelId: string): boolean {
  return MODELS_WITH_FAST_MODE.has(normalizeModelId(modelId));
}

export function getFastModeOptions(
  modelId: string,
): { value: string; name: string }[] | null {
  if (!supportsFastMode(modelId)) return null;
  return [
    { value: "on", name: "On" },
    { value: "off", name: "Off" },
  ];
}

// cooldown keeps the toggle on (user intent); only an explicit off clears it.
export function fastModeStateEnabled(state: string | undefined): boolean {
  return state !== undefined && state !== "off";
}

interface EffortOption {
  value: EffortLevel;
  name: string;
  _meta?: Record<string, unknown>;
}

function effortOptionMeta(
  value: EffortLevel,
): Record<string, unknown> | undefined {
  const docsUrl = EFFORT_LEVEL_DOCS_URLS[value];
  const meta: Record<string, unknown> = {
    ...(value === DEFAULT_EFFORT ? { [DEFAULT_OPTION_META_KEY]: true } : {}),
    ...(docsUrl ? { [OPTION_DOCS_URL_META_KEY]: docsUrl } : {}),
  };
  return Object.keys(meta).length > 0 ? meta : undefined;
}

/** Null rather than an empty list for a model with no effort control, so the caller
 * renders no dropdown instead of an empty one. */
export function getEffortOptions(modelId: string): EffortOption[] | null {
  const levels = effortLevelsFor(modelId);
  if (levels.length === 0) return null;
  return levels.map((value) => ({
    value,
    name: EFFORT_LEVEL_LABELS[value],
    _meta: effortOptionMeta(value),
  }));
}

// Model alias resolution — lets callers use human-friendly aliases like
// "opus" or "sonnet" instead of full model IDs like "claude-opus-4-8".

const MODEL_CONTEXT_HINT_PATTERN = /\[(\d+m)\]$/i;

function tokenizeModelPreference(model: string): {
  tokens: string[];
  contextHint?: string;
} {
  const lower = model.trim().toLowerCase();
  const contextHint = lower
    .match(MODEL_CONTEXT_HINT_PATTERN)?.[1]
    ?.toLowerCase();

  const normalized = lower.replace(MODEL_CONTEXT_HINT_PATTERN, " $1 ");
  const rawTokens = normalized.split(/[^a-z0-9]+/).filter(Boolean);
  const tokens = rawTokens
    .map((token) => {
      if (token === "opusplan") return "opus";
      if (token === "best" || token === "default") return "";
      return token;
    })
    .filter((token) => token && token !== "claude")
    .filter((token) => /[a-z]/.test(token) || token.endsWith("m"));

  return { tokens, contextHint };
}

interface ModelOption {
  value: string;
  name?: string;
  description?: string;
}

// Captures a model family version: `4-6`/`4.7` for dated generations, or a
// bare `5` for single-number ones like "Sonnet 5". Used to keep a pinned
// `claude-opus-4-7` from matching the `opus` alias once it points at 4.8.
const MODEL_FAMILY_VERSION_PATTERN = /\b(\d+)(?:[-.](\d+))?\b/;

function extractModelFamilyVersion(s: string | undefined): string | null {
  if (!s) return null;
  // Strip "[1m]"-style context hints first — that digit is context window
  // size, not a model generation version.
  const match = s.replace(/\[\d+m\]/gi, "").match(MODEL_FAMILY_VERSION_PATTERN);
  if (!match) return null;
  return match[2] ? `${match[1]}.${match[2]}` : match[1];
}

function modelVersionsCompatible(
  preference: string,
  candidate: ModelOption,
): boolean {
  const preferred = extractModelFamilyVersion(preference);
  if (!preferred) return true;
  const candidateVersion =
    extractModelFamilyVersion(candidate.value) ??
    extractModelFamilyVersion(candidate.name) ??
    extractModelFamilyVersion(candidate.description);
  if (!candidateVersion) return true;
  return preferred === candidateVersion;
}

function scoreModelMatch(
  model: ModelOption,
  tokens: string[],
  contextHint?: string,
): number {
  const haystack = `${model.value} ${model.name ?? ""}`.toLowerCase();
  let score = 0;
  let nonHintMatched = false;
  for (const token of tokens) {
    if (haystack.includes(token)) {
      if (token !== contextHint) nonHintMatched = true;
      score += token === contextHint ? 3 : 1;
    }
  }
  if (contextHint && !nonHintMatched) return 0;
  return score;
}

export function resolveModelPreference(
  preference: string,
  options: ModelOption[],
): string | null {
  const trimmed = preference.trim();
  if (!trimmed) return null;

  const lower = trimmed.toLowerCase();

  // Exact match on value or display name
  const directMatch = options.find(
    (o) =>
      o.value === trimmed ||
      o.value.toLowerCase() === lower ||
      (o.name && o.name.toLowerCase() === lower),
  );
  if (directMatch) return directMatch.value;

  // Substring match
  const includesMatch = options.find((o) => {
    if (!modelVersionsCompatible(trimmed, o)) return false;
    const value = o.value.toLowerCase();
    const display = (o.name ?? "").toLowerCase();
    return (
      value.includes(lower) || display.includes(lower) || lower.includes(value)
    );
  });
  if (includesMatch) return includesMatch.value;

  // Tokenized matching for aliases like "opus[1m]"
  const { tokens, contextHint } = tokenizeModelPreference(trimmed);
  if (tokens.length === 0) return null;

  let bestMatch: ModelOption | null = null;
  let bestScore = 0;
  for (const model of options) {
    if (!modelVersionsCompatible(trimmed, model)) continue;
    const score = scoreModelMatch(model, tokens, contextHint);
    if (0 < score && (!bestMatch || bestScore < score)) {
      bestMatch = model;
      bestScore = score;
    }
  }

  return bestMatch?.value ?? null;
}
