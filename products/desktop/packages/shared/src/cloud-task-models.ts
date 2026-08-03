import type { Adapter } from "./adapter";
import { CODEX_MODE_PRESETS } from "./execution-modes";
import { restrictedModelMeta } from "./models";
import { getReasoningEffortOptions } from "./reasoning-effort";

export interface GatewayModel {
  id: string;
  owned_by: string;
  context_window: number;
  supports_streaming: boolean;
  supports_vision: boolean;
  allowed: boolean;
  restriction_reason?: string | null;
}

interface GatewayModelsResponse {
  data?: unknown[];
  models?: unknown[];
}

export interface CloudTaskConfigSelectOption {
  value: string;
  name: string;
  description?: string;
  _meta?: Record<string, unknown>;
}

export interface CloudTaskConfigOption {
  id: string;
  name: string;
  type: "select";
  currentValue: string;
  options: CloudTaskConfigSelectOption[];
  category: "mode" | "model" | "thought_level";
  description: string;
}

export interface CloudTaskModePreset {
  id: string;
  name: string;
  description: string;
}

export const DEFAULT_GATEWAY_MODEL = "claude-opus-4-8";

export const DEFAULT_CODEX_MODEL = "gpt-5.5";

export const BLOCKED_GATEWAY_MODEL_IDS = [
  "gpt-5-mini",
  "openai/gpt-5-mini",
  "gpt-5.2",
  "openai/gpt-5.2",
  "gpt-5.3",
  "openai/gpt-5.3",
  "gpt-5.3-codex",
  "openai/gpt-5.3-codex",
  "claude-opus-4-5",
  "anthropic/claude-opus-4-5",
  "claude-opus-4-6",
  "anthropic/claude-opus-4-6",
  "claude-sonnet-4-5",
  "anthropic/claude-sonnet-4-5",
  "claude-haiku-4-5",
  "anthropic/claude-haiku-4-5",
] as const;

const BLOCKED_GATEWAY_MODELS = new Set<string>(BLOCKED_GATEWAY_MODEL_IDS);

const CLAUDE_MODE_PRESETS: readonly CloudTaskModePreset[] = [
  {
    id: "default",
    name: "Default",
    description: "Standard behavior, prompts for dangerous operations",
  },
  {
    id: "acceptEdits",
    name: "Accept Edits",
    description: "Auto-accept file edit operations",
  },
  {
    id: "plan",
    name: "Plan Mode",
    description: "Planning mode, no actual tool execution",
  },
  {
    id: "bypassPermissions",
    name: "Bypass Permissions",
    description: "Auto-accept all permission requests",
  },
  {
    id: "auto",
    name: "Auto Mode",
    description: "Auto-approve file edits and shell commands",
  },
];

const PROVIDER_NAMES: Record<string, string> = {
  anthropic: "Anthropic",
  openai: "OpenAI",
  "google-vertex": "Gemini",
};

const MODEL_FAMILY_ORDER = ["fable", "opus", "sonnet", "haiku"];
const PROVIDER_PREFIXES = ["anthropic/", "openai/", "google-vertex/"];
const KNOWN_ACRONYMS = new Set(["gpt", "glm"]);
const MODEL_CONTEXT_WINDOW_OVERRIDES: Readonly<Record<string, number>> = {
  "@cf/zai-org/glm-5.2": 1_000_000,
};

export function getCloudTaskGatewayUrl(posthogHost: string): string {
  const url = new URL(posthogHost);
  let gatewayBaseUrl: string;

  if (url.hostname === "localhost" || url.hostname === "127.0.0.1") {
    gatewayBaseUrl = `${url.protocol}//localhost:3308`;
  } else if (url.hostname === "host.docker.internal") {
    gatewayBaseUrl = `${url.protocol}//host.docker.internal:3308`;
  } else if (url.hostname === "app.dev.posthog.dev") {
    gatewayBaseUrl = "https://gateway.dev.posthog.dev";
  } else {
    const region = url.hostname.match(/^(us|eu)\.posthog\.com$/)?.[1] ?? "us";
    gatewayBaseUrl = `https://gateway.${region}.posthog.com`;
  }

  return `${gatewayBaseUrl}/posthog_code`;
}

function isGatewayModel(value: unknown): value is Partial<GatewayModel> & {
  id: string;
} {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as { id?: unknown }).id === "string"
  );
}

export function normalizeGatewayModelsResponse(value: unknown): GatewayModel[] {
  const response = value as GatewayModelsResponse;
  const entries = Array.isArray(value)
    ? value
    : Array.isArray(response?.data)
      ? response.data
      : Array.isArray(response?.models)
        ? response.models
        : [];

  return entries
    .filter(isGatewayModel)
    .filter((model) => !isBlockedModelId(model.id))
    .map((model) => ({
      id: model.id,
      owned_by: model.owned_by ?? "",
      context_window: Math.max(
        model.context_window ?? 0,
        MODEL_CONTEXT_WINDOW_OVERRIDES[model.id] ?? 0,
      ),
      supports_streaming: model.supports_streaming ?? false,
      supports_vision: model.supports_vision ?? false,
      allowed: model.allowed !== false,
      restriction_reason: model.restriction_reason ?? null,
    }));
}

export function isBlockedModelId(modelId: string): boolean {
  return BLOCKED_GATEWAY_MODELS.has(modelId.toLowerCase());
}

export function isAnthropicModel(model: GatewayModel): boolean {
  if (model.owned_by) {
    return model.owned_by === "anthropic";
  }
  return model.id.startsWith("claude-") || model.id.startsWith("anthropic/");
}

export function isOpenAIModel(model: GatewayModel): boolean {
  if (model.owned_by) {
    return model.owned_by === "openai";
  }
  return model.id.startsWith("gpt-") || model.id.startsWith("openai/");
}

export function isCloudflareModelId(modelId: string): boolean {
  return modelId.startsWith("@cf/");
}

export function isGlmModelId(modelId: string): boolean {
  return modelId.toLowerCase().includes("glm");
}

export function isCloudflareModel(model: GatewayModel): boolean {
  return isCloudflareModelId(model.id) || model.owned_by === "cloudflare";
}

export function isModalModelId(modelId: string): boolean {
  return modelId === "moonshotai/kimi-k3";
}

export function isModalModel(model: GatewayModel): boolean {
  return isModalModelId(model.id) || model.owned_by === "modal";
}

export function pickAllowedModel(
  models: ReadonlyArray<Pick<GatewayModel, "id" | "allowed">>,
  preferred: string,
): string {
  if (models.length === 0) return preferred;
  const preferredEntry = models.find((model) => model.id === preferred);
  if (!preferredEntry || preferredEntry.allowed) return preferred;
  const allowed = models.filter((model) => model.allowed);
  if (allowed.length === 0) return preferred;
  return allowed.reduce((best, candidate) =>
    getClaudeModelRecency(candidate.id) >= getClaudeModelRecency(best.id)
      ? candidate
      : best,
  ).id;
}

export function getProviderName(ownedBy: string): string {
  return PROVIDER_NAMES[ownedBy] ?? ownedBy;
}

export function getClaudeModelRecency(modelId: string): number {
  const match = modelId.toLowerCase().match(/-(\d+)(?:[-.](\d+))?/);
  if (!match) return Number.MAX_SAFE_INTEGER;
  const major = Number(match[1]);
  const minor = match[2] ? Number(match[2]) : 0;
  return major * 1000 + minor;
}

function getModelFamilyRank(modelId: string): number {
  const normalizedModelId = modelId.toLowerCase();
  const index = MODEL_FAMILY_ORDER.findIndex((family) =>
    normalizedModelId.includes(family),
  );
  return index === -1 ? MODEL_FAMILY_ORDER.length : index;
}

export function compareModelsForPicker(a: string, b: string): number {
  const familyDiff = getModelFamilyRank(a) - getModelFamilyRank(b);
  if (familyDiff !== 0) return familyDiff;
  return getClaudeModelRecency(b) - getClaudeModelRecency(a);
}

function stripProviderPrefix(modelId: string): string {
  for (const prefix of PROVIDER_PREFIXES) {
    if (modelId.startsWith(prefix)) {
      return modelId.slice(prefix.length);
    }
  }
  return modelId;
}

function formatProviderModelName(modelId: string): string {
  const [acronym, version, ...suffix] = modelId.split("-");
  if (!KNOWN_ACRONYMS.has(acronym.toLowerCase())) return modelId.toLowerCase();
  const head = version
    ? `${acronym.toUpperCase()}-${version}`
    : acronym.toUpperCase();
  const tail = suffix.map(
    (word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase(),
  );
  return [head, ...tail].join(" ");
}

export function formatGatewayModelName(model: GatewayModel): string {
  if (isCloudflareModel(model)) {
    return formatProviderModelName(model.id.split("/").pop() ?? model.id);
  }
  if (isModalModel(model)) {
    return formatModelId(model.id.split("/").pop() ?? model.id);
  }
  if (isOpenAIModel(model)) {
    return formatProviderModelName(stripProviderPrefix(model.id));
  }
  return formatModelId(model.id);
}

export function formatModelId(modelId: string): string {
  const cleanId = stripProviderPrefix(modelId).replace(/(\d)-(\d)/g, "$1.$2");
  return cleanId
    .split(/[-_]/)
    .map((word) => {
      if (/^[0-9.]+$/.test(word)) return word;
      return word.charAt(0).toUpperCase() + word.slice(1).toLowerCase();
    })
    .join(" ");
}

function getAdapterModels(
  models: readonly GatewayModel[],
  adapter: Adapter,
): GatewayModel[] {
  return models.filter((model) =>
    adapter === "codex"
      ? isOpenAIModel(model)
      : isAnthropicModel(model) ||
        isCloudflareModel(model) ||
        isModalModel(model),
  );
}

function getModeOptions(
  adapter: Adapter,
  modePresets?: readonly CloudTaskModePreset[],
): CloudTaskConfigSelectOption[] {
  const modes =
    modePresets ??
    (adapter === "codex" ? CODEX_MODE_PRESETS : CLAUDE_MODE_PRESETS);
  return modes.map((mode) => ({
    value: mode.id,
    name: mode.name,
    description: mode.description,
  }));
}

export function buildCloudTaskConfigOptions(
  models: readonly GatewayModel[],
  adapter: Adapter,
  modePresets?: readonly CloudTaskModePreset[],
): CloudTaskConfigOption[] {
  const adapterModels = getAdapterModels(models, adapter);
  const modelOptions: CloudTaskConfigSelectOption[] = adapterModels.map(
    (model) => ({
      value: model.id,
      name: formatGatewayModelName(model),
      description: `Context: ${model.context_window.toLocaleString()} tokens`,
      ...(model.allowed ? {} : { _meta: restrictedModelMeta() }),
    }),
  );

  if (adapter === "claude") {
    modelOptions.sort(
      (a, b) => getClaudeModelRecency(a.value) - getClaudeModelRecency(b.value),
    );
  }

  const defaultModel =
    adapter === "codex"
      ? (modelOptions.find((option) => option.value === DEFAULT_CODEX_MODEL)
          ?.value ??
        modelOptions[0]?.value ??
        "")
      : DEFAULT_GATEWAY_MODEL;
  const preferredModelId = modelOptions.some(
    (option) => option.value === defaultModel,
  )
    ? defaultModel
    : (modelOptions[0]?.value ?? defaultModel);
  const resolvedModelId = pickAllowedModel(adapterModels, preferredModelId);

  if (!modelOptions.some((option) => option.value === resolvedModelId)) {
    modelOptions.unshift({
      value: resolvedModelId,
      name: resolvedModelId,
      description: "Custom model",
    });
  }

  const configOptions: CloudTaskConfigOption[] = [
    {
      id: "mode",
      name: "Approval Preset",
      type: "select",
      currentValue: adapter === "codex" ? "auto" : "plan",
      options: getModeOptions(adapter, modePresets),
      category: "mode",
      description: "Choose an approval and sandboxing preset for your session",
    },
    {
      id: "model",
      name: "Model",
      type: "select",
      currentValue: resolvedModelId,
      options: modelOptions,
      category: "model",
      description: "Choose which model the agent should use",
    },
  ];

  const reasoningOptions = getReasoningEffortOptions(adapter, resolvedModelId);
  if (reasoningOptions) {
    configOptions.push({
      id: adapter === "codex" ? "reasoning_effort" : "effort",
      name: adapter === "codex" ? "Reasoning Level" : "Effort",
      type: "select",
      currentValue: "high",
      options: reasoningOptions,
      category: "thought_level",
      description:
        adapter === "codex"
          ? "Controls how much reasoning effort the model uses"
          : "Controls how much effort Claude puts into its response",
    });
  }

  return configOptions;
}
