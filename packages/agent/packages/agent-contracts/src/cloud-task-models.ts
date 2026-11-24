import type { Adapter } from "./adapter";
import { getCustomCloud, isCustomCloudHost } from "./custom-cloud";
import { CODEX_MODE_PRESETS } from "./execution-modes";
import {
  ANTHROPIC_MESSAGES_SHAPE,
  adapterForListedModel,
  DEFAULT_MODEL_BY_RUNTIME_ADAPTER,
  knownGatewayModels,
  type ListedModel,
  listedModelFor,
  listedName,
  OPENAI_RESPONSES_SHAPE,
  offeredModelsOf,
  rememberGatewayModels,
} from "./model-catalog";
import {
  customModelMeta,
  modelHarnessMeta,
  restrictedModelMeta,
} from "./models";
import { getReasoningEffortOptions } from "./reasoning-effort";

export interface GatewayModel extends ListedModel {
  owned_by: string;
  context_window: number;
  supports_streaming: boolean;
  supports_vision: boolean;
  allowed: boolean;
  restriction_reason?: string | null;
}

export { ANTHROPIC_MESSAGES_SHAPE, OPENAI_RESPONSES_SHAPE };

export const GATEWAY_LISTING_META_KEY = "posthog/gatewayListing";

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

export interface CloudTaskConfigSelectGroup {
  group: string;
  name: string;
  options: CloudTaskConfigSelectOption[];
}

export interface CloudTaskConfigOption {
  id: string;
  name: string;
  type: "select";
  currentValue: string;
  options: CloudTaskConfigSelectOption[];
  category: "mode" | "model" | "thought_level";
  description: string;
  _meta?: Record<string, unknown>;
}

export interface CloudTaskModePreset {
  id: string;
  name: string;
  description: string;
}

export const DEFAULT_GATEWAY_MODEL = "claude-opus-5-5";

export const DEFAULT_CODEX_MODEL = DEFAULT_MODEL_BY_RUNTIME_ADAPTER.codex;

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

const MODEL_FAMILY_ORDER = ["fable", "opus", "sonnet", "haiku"];
const PROVIDER_PREFIXES = ["anthropic/", "openai/", "google-vertex/"];
const KNOWN_ACRONYMS = new Set(["gpt", "glm"]);

export function getCloudTaskGatewayUrl(posthogHost: string): string {
  const url = new URL(posthogHost);
  let gatewayBaseUrl: string;
  const custom = getCustomCloud();

  if (custom?.gatewayUrl && isCustomCloudHost(posthogHost)) {
    gatewayBaseUrl = custom.gatewayUrl.replace(/\/+$/, "");
  } else if (url.hostname === "localhost" || url.hostname === "127.0.0.1") {
    gatewayBaseUrl = `${url.protocol}//localhost:8080`;
  } else if (url.hostname === "host.docker.internal") {
    gatewayBaseUrl = `${url.protocol}//host.docker.internal:8080`;
  } else if (url.hostname === "app.dev.posthog.dev") {
    gatewayBaseUrl = "https://ai-gateway.dev.posthog.dev";
  } else {
    const region = url.hostname.match(/^(us|eu)\.posthog\.com$/)?.[1] ?? "us";
    gatewayBaseUrl = `https://ai-gateway.${region}.posthog.com`;
  }

  return gatewayBaseUrl;
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

function isString(value: unknown): value is string {
  return typeof value === "string";
}

function listedFacts(row: object): Partial<ListedModel> {
  const { name, family, release_date, reasoning, pricing } = row as {
    name?: unknown;
    family?: unknown;
    release_date?: unknown;
    reasoning?: { efforts?: unknown } | null;
    pricing?: { prompt?: unknown; completion?: unknown } | null;
  };
  const efforts = reasoning?.efforts;
  const price = (value: unknown): number | undefined =>
    Number(value) > 0
      ? Number((Number(value) * 1_000_000).toFixed(6))
      : undefined;
  return {
    ...(isString(name) ? { name } : {}),
    ...(isString(family) ? { family } : {}),
    ...(isString(release_date) ? { release_date } : {}),
    ...(reasoning !== undefined
      ? {
          reasoning_efforts: Array.isArray(efforts)
            ? efforts.filter(isString)
            : [],
        }
      : {}),
    input_per_mtok: price(pricing?.prompt),
    output_per_mtok: price(pricing?.completion),
  };
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

  const models = entries.filter(isGatewayModel).map((model) => ({
    id: model.id,
    owned_by: model.owned_by ?? "",
    context_window: model.context_window ?? 0,
    supports_streaming: model.supports_streaming ?? false,
    supports_vision: model.supports_vision ?? false,
    allowed: model.allowed !== false,
    restriction_reason: model.restriction_reason ?? null,
    ...(Array.isArray(model.api_shapes)
      ? { api_shapes: model.api_shapes.filter(isString) }
      : {}),
    ...listedFacts(model),
  }));
  rememberGatewayModels(models);
  return offeredModelsOf(models);
}

export type GatewayModelRow = Pick<
  GatewayModel,
  | "id"
  | "owned_by"
  | "context_window"
  | "allowed"
  | "restriction_reason"
  | "api_shapes"
  | "name"
> & { reasoning?: { efforts: string[] } };

interface TaskModelChoice {
  runtime_adapter?: unknown;
  model?: unknown;
  display_name?: unknown;
  supported_efforts?: unknown;
  context_window?: unknown;
  allowed?: unknown;
}

export const TASK_MODELS_FETCH_TIMEOUT_MS = 10_000;

// The Go gateway lists each PostHog-hosted model on all three of these.
const SERVED_MODEL_SHAPES = [
  "openai-chat-completions",
  OPENAI_RESPONSES_SHAPE,
  ANTHROPIC_MESSAGES_SHAPE,
];

export function taskModelsUrl(apiHost: string, projectId: number): string {
  return `${apiHost.replace(/\/+$/, "")}/api/projects/${projectId}/tasks/models/`;
}

function taskModelRow(choice: TaskModelChoice): GatewayModelRow | null {
  if (typeof choice.model !== "string") return null;
  const id = choice.model;
  const runtimeAdapter =
    choice.runtime_adapter === "codex" ? "codex" : "claude";
  const served = isServedModelId(id, runtimeAdapter);
  const allowed = choice.allowed !== false;
  return {
    id,
    owned_by: served
      ? "posthog"
      : runtimeAdapter === "codex"
        ? "openai"
        : "anthropic",
    context_window:
      typeof choice.context_window === "number" ? choice.context_window : 0,
    allowed,
    restriction_reason: allowed ? null : PAID_PLAN_REQUIRED_REASON,
    ...(isString(choice.display_name) ? { name: choice.display_name } : {}),
    ...(Array.isArray(choice.supported_efforts)
      ? { reasoning: { efforts: choice.supported_efforts.filter(isString) } }
      : {}),
    api_shapes: served
      ? SERVED_MODEL_SHAPES
      : [
          runtimeAdapter === "codex"
            ? OPENAI_RESPONSES_SHAPE
            : ANTHROPIC_MESSAGES_SHAPE,
        ],
  };
}

export function gatewayModelRowsFromTaskModels(
  value: unknown,
): GatewayModelRow[] {
  const models = (value as { models?: unknown } | null)?.models;
  if (!Array.isArray(models)) return [];
  return models
    .filter(
      (choice): choice is TaskModelChoice =>
        typeof choice === "object" && choice !== null,
    )
    .map(taskModelRow)
    .filter((row): row is GatewayModelRow => row !== null);
}

export function isAnthropicModel(model: GatewayModel): boolean {
  if (model.owned_by) {
    return model.owned_by === "anthropic";
  }
  return model.id.startsWith("claude-") || model.id.startsWith("anthropic/");
}

export function isAnthropicModelId(modelId: string): boolean {
  return modelId.startsWith("claude-") || modelId.startsWith("anthropic/");
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

export function isCloudflareModel(model: GatewayModel): boolean {
  return isCloudflareModelId(model.id) || model.owned_by === "cloudflare";
}

export function isModalModelId(modelId: string): boolean {
  return (
    modelId === "moonshotai/kimi-k3" || modelId === "moonshotai/kimi-k3.1-pro"
  );
}

export function isModalModel(model: GatewayModel): boolean {
  return isModalModelId(model.id) || model.owned_by === "modal";
}

export function isDeepseekModelId(modelId: string): boolean {
  return modelId.toLowerCase().includes("deepseek");
}

export function isBasetenModel(model: GatewayModel): boolean {
  return isDeepseekModelId(model.id) || model.owned_by === "baseten";
}

export function isServedModelId(
  modelId: string,
  adapter: Adapter | undefined = listedAdapter(modelId),
): boolean {
  return (
    isModalModelId(modelId) ||
    isDeepseekModelId(modelId) ||
    (modelId.includes("/") &&
      !isAnthropicModelId(modelId) &&
      !isCloudflareModelId(modelId) &&
      adapter === "claude")
  );
}

function listedAdapter(modelId: string): Adapter | undefined {
  const listed = listedModelFor(modelId);
  return listed && adapterForListedModel(listed);
}

export function isClaudeAdapterModel(model: GatewayModel): boolean {
  if (model.api_shapes?.length) {
    return adapterForListedModel(model) === "claude";
  }
  return (
    isAnthropicModel(model) ||
    isCloudflareModel(model) ||
    isModalModel(model) ||
    isBasetenModel(model)
  );
}

export function isCodexAdapterModel(model: GatewayModel): boolean {
  if (model.api_shapes?.length) {
    return adapterForListedModel(model) === "codex";
  }
  return isOpenAIModel(model);
}

export function isClaudeAdapterModelId(modelId: string): boolean {
  return (
    isAnthropicModelId(modelId) ||
    isCloudflareModelId(modelId) ||
    isModalModelId(modelId) ||
    isDeepseekModelId(modelId) ||
    listedAdapter(modelId) === "claude"
  );
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

const PROVIDER_NAMES: Record<string, string> = {
  anthropic: "Anthropic",
  openai: "OpenAI",
  "google-vertex": "Gemini",
};

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

export function formatGatewayModelName(model: GatewayModel): string {
  return (
    listedName(model) ?? formatModelId(model.id.split("/").pop() ?? model.id)
  );
}

function titled(word: string): string {
  if (/^[0-9.]+$/.test(word)) return word;
  return word.charAt(0).toUpperCase() + word.slice(1).toLowerCase();
}

export function formatModelId(modelId: string): string {
  const cleanId = stripProviderPrefix(modelId).replace(/(\d)-(\d)/g, "$1.$2");
  const [first, version, ...rest] = cleanId.split(/[-_]/);
  if (!KNOWN_ACRONYMS.has(first.toLowerCase())) {
    return cleanId.split(/[-_]/).map(titled).join(" ");
  }
  const head = version
    ? `${first.toUpperCase()}-${version}`
    : first.toUpperCase();
  return [head, ...rest.map(titled)].join(" ");
}

function getAdapterModels(
  models: readonly GatewayModel[],
  adapter: Adapter,
): GatewayModel[] {
  return models.filter((model) =>
    adapter === "codex"
      ? isCodexAdapterModel(model)
      : isClaudeAdapterModel(model),
  );
}

export function adapterForModelId(modelId: string): Adapter {
  const normalized = modelId.toLowerCase();
  return normalized.startsWith("gpt-") || normalized.startsWith("openai/")
    ? "codex"
    : "claude";
}

function buildModelSelectOptions(
  models: readonly GatewayModel[],
  adapter: Adapter,
): CloudTaskConfigSelectOption[] {
  const options = getAdapterModels(models, adapter).map((model) => ({
    value: model.id,
    name: formatGatewayModelName(model),
    description: `Context: ${model.context_window.toLocaleString()} tokens`,
    _meta: {
      ...modelHarnessMeta(adapter),
      ...(model.allowed ? {} : restrictedModelMeta()),
    },
  }));
  if (adapter === "claude") {
    options.sort(
      (a, b) => getClaudeModelRecency(a.value) - getClaudeModelRecency(b.value),
    );
  }
  return options;
}

const MODEL_VENDOR_NAMES: Record<string, string> = {
  "zai-org": "Z.ai",
  moonshotai: "Moonshot AI",
  "deepseek-ai": "DeepSeek",
  "google-vertex": "Gemini",
  meta: "Meta",
};

const VENDOR_GROUP_ORDER = ["anthropic", "openai"];

function modelVendor(modelId: string): { key: string; name: string } {
  const normalized = modelId.toLowerCase().replace(/^@cf\//, "");
  if (normalized.startsWith("claude-") || normalized.startsWith("anthropic/")) {
    return { key: "anthropic", name: "Anthropic" };
  }
  if (normalized.startsWith("gpt-") || normalized.startsWith("openai/")) {
    return { key: "openai", name: "OpenAI" };
  }
  const org = normalized.split("/")[0];
  const name = MODEL_VENDOR_NAMES[org];
  if (name) return { key: org, name };
  return { key: "other", name: "Other" };
}

/**
 * Model options for every harness, grouped by the model's vendor, so every
 * picker offers one identical catalog and the harness is derived from the
 * pick. Each option keeps its harness stamp in _meta; a currentValue missing
 * from the catalog is kept as a custom entry under its own vendor.
 */
export function buildProviderModelGroups(
  models: readonly GatewayModel[],
  adapter: Adapter,
  currentValue?: string,
): CloudTaskConfigSelectGroup[] {
  const groups: CloudTaskConfigSelectGroup[] = [];
  const groupsByVendor = new Map<string, CloudTaskConfigSelectGroup>();
  const groupFor = (modelId: string): CloudTaskConfigSelectGroup => {
    const vendor = modelVendor(modelId);
    let group = groupsByVendor.get(vendor.key);
    if (!group) {
      group = { group: vendor.key, name: vendor.name, options: [] };
      groupsByVendor.set(vendor.key, group);
      groups.push(group);
    }
    return group;
  };

  const harnesses: Adapter[] = ["claude", "codex"];
  for (const option of harnesses.flatMap((harness) =>
    buildModelSelectOptions(models, harness),
  )) {
    groupFor(option.value).options.push(option);
  }
  for (const group of groups) {
    group.options.sort((a, b) => compareModelsForPicker(a.value, b.value));
  }

  const hasCurrent =
    !currentValue ||
    groups.some((group) =>
      group.options.some((option) => option.value === currentValue),
    );
  if (!hasCurrent && currentValue) {
    // The current selection has to stay offered even when a gateway blip
    // answers with an empty or partial catalog, so keep it as a custom entry
    // stamped with the harness it is running on.
    groupFor(currentValue).options.unshift({
      value: currentValue,
      name: currentValue,
      description: "Custom model",
      _meta: {
        ...modelHarnessMeta(adapter),
        ...customModelMeta(),
      },
    });
  }

  const vendorRank = (key: string): number => {
    const index = VENDOR_GROUP_ORDER.indexOf(key);
    return index === -1 ? VENDOR_GROUP_ORDER.length : index;
  };
  return groups.sort((a, b) => vendorRank(a.group) - vendorRank(b.group));
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
  const modelOptions = buildModelSelectOptions(models, adapter);

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
      _meta: customModelMeta(),
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
      _meta: { [GATEWAY_LISTING_META_KEY]: knownGatewayModels() },
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

export function rememberGatewayListingFrom(
  options: ReadonlyArray<{
    category?: string | null;
    _meta?: Record<string, unknown> | null;
  }>,
): void {
  const listing = options.find((option) => option.category === "model")
    ?._meta?.[GATEWAY_LISTING_META_KEY];
  if (Array.isArray(listing)) {
    rememberGatewayModels(listing as ListedModel[]);
  }
}

export const PAID_PLAN_REQUIRED_REASON = "paid_plan_required";

export interface AllowedModelsPin {
  /** The desktop product's model list; empty keeps every entry. */
  productModels: readonly string[];
  /** What the token can call; null (the dev override) allows every entry. */
  allowedModels: readonly string[] | null;
}

function modelNames(entry: Record<string, unknown>): string[] {
  const names = typeof entry.id === "string" ? [entry.id] : [];
  // The mint echoes the pin in canonical spelling (`anthropic/claude-opus-4.8`).
  if (typeof entry.canonical === "string") names.push(entry.canonical);
  if (Array.isArray(entry.aliases)) {
    for (const alias of entry.aliases) {
      if (typeof alias === "string") names.push(alias);
    }
  }
  return names;
}

/**
 * Filters the Go gateway's unfiltered `/v1/models` body to the desktop product
 * list and marks `allowed` from the token's pin, keeping the response shape.
 */
export function applyAllowedModels(
  body: unknown,
  pin: AllowedModelsPin,
): unknown {
  const product = new Set(pin.productModels);
  const allowed = pin.allowedModels && new Set(pin.allowedModels);
  const rewrite = (entries: unknown[]): unknown[] =>
    entries.flatMap((entry) => {
      if (!entry || typeof entry !== "object") return [];
      const record = entry as Record<string, unknown>;
      const names = modelNames(record);
      if (names.length === 0) return [];
      if (product.size > 0 && !names.some((name) => product.has(name))) {
        return [];
      }
      const isAllowed =
        allowed === null || names.some((name) => allowed.has(name));
      return [
        {
          ...record,
          allowed: isAllowed,
          restriction_reason: isAllowed ? null : PAID_PLAN_REQUIRED_REASON,
        },
      ];
    });

  if (Array.isArray(body)) return rewrite(body);
  if (!body || typeof body !== "object") return body;
  const response = body as GatewayModelsResponse & Record<string, unknown>;
  if (Array.isArray(response.data)) {
    return { ...response, data: rewrite(response.data) };
  }
  if (Array.isArray(response.models)) {
    return { ...response, models: rewrite(response.models) };
  }
  return body;
}
