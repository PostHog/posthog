export interface GatewayModel {
  id: string;
  owned_by: string;
  context_window: number;
  supports_streaming: boolean;
  supports_vision: boolean;
  // Free-tier model gate: authenticated fetches mark models outside the
  // caller's plan `allowed: false`. Anonymous fetches and older gateways
  // don't mark, so absence means allowed.
  allowed: boolean;
  restriction_reason?: string | null;
}

interface GatewayModelsResponse {
  object: "list";
  data: Array<Omit<GatewayModel, "allowed"> & { allowed?: boolean }>;
}

export interface FetchGatewayModelsOptions {
  gatewayUrl: string;
  /** Bearer token; required for accurate free-tier marks. */
  authToken?: string;
}

export const DEFAULT_GATEWAY_MODEL = "claude-opus-4-8";

export const DEFAULT_CODEX_MODEL = "gpt-5.5";

const BLOCKED_MODELS = new Set([
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
]);

export function isBlockedModelId(modelId: string): boolean {
  return BLOCKED_MODELS.has(modelId.toLowerCase());
}

interface ModelsListEntry {
  id?: string;
  owned_by?: string;
  allowed?: boolean;
  restriction_reason?: string | null;
}

type ModelsListResponse =
  | {
      data?: ModelsListEntry[];
      models?: ModelsListEntry[];
    }
  | ModelsListEntry[];

const CACHE_TTL = 10 * 60 * 1000; // 10 minutes

// Bound the gateway /v1/models request so a stalled connection cannot hold up
// session init: this fetch runs inside the Promise.all that gates the 30s SDK
// initialization timeout, so it must resolve well within that window. On abort
// the callers fall through to `return []`.
const GATEWAY_FETCH_TIMEOUT_MS = 10_000;

const MODEL_CONTEXT_WINDOW_OVERRIDES: Readonly<Record<string, number>> = {
  "@cf/zai-org/glm-5.2": 1_000_000,
};

// Restriction marks are identity-scoped (free-tier marks are authed-only and
// differ per org), so cache entries are keyed on the exact token — an org
// switch in the same process must never be served the old org's marks. A
// token rotation just costs one refetch.
interface ModelsCache<T> {
  models: T[];
  expiry: number;
  url: string;
  token: string | null;
}

function readModelsCache<T>(
  cache: ModelsCache<T> | null,
  url: string,
  token: string | null,
): T[] | null {
  if (!cache || cache.url !== url || cache.token !== token) return null;
  return Date.now() < cache.expiry ? cache.models : null;
}

function authHeaders(authToken?: string): Record<string, string> | undefined {
  return authToken ? { Authorization: `Bearer ${authToken}` } : undefined;
}

let gatewayModelsCache: ModelsCache<GatewayModel> | null = null;

export async function fetchGatewayModels(
  options?: FetchGatewayModelsOptions,
): Promise<GatewayModel[]> {
  const gatewayUrl = options?.gatewayUrl ?? process.env.ANTHROPIC_BASE_URL;
  if (!gatewayUrl) {
    return [];
  }

  const token = options?.authToken ?? null;
  const cached = readModelsCache(gatewayModelsCache, gatewayUrl, token);
  if (cached) return cached;

  const modelsUrl = `${gatewayUrl}/v1/models`;

  try {
    const response = await fetch(modelsUrl, {
      headers: authHeaders(options?.authToken),
      signal: AbortSignal.timeout(GATEWAY_FETCH_TIMEOUT_MS),
    });

    if (!response.ok) {
      return [];
    }

    const data = (await response.json()) as GatewayModelsResponse;
    const models = (data.data ?? [])
      .filter((m) => !isBlockedModelId(m.id))
      .map((m) => ({
        ...m,
        context_window: Math.max(
          m.context_window,
          MODEL_CONTEXT_WINDOW_OVERRIDES[m.id] ?? 0,
        ),
        allowed: m.allowed !== false,
      }));
    gatewayModelsCache = {
      models,
      expiry: Date.now() + CACHE_TTL,
      url: gatewayUrl,
      token,
    };
    return models;
  } catch {
    return [];
  }
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

// Cloudflare Workers AI model ids carry the `@cf/` path prefix (e.g. `@cf/zai-org/glm-5.2`). Kept as
// a standalone id-only check so callers that only have a model id (not a full GatewayModel) — like the
// Claude adapter's desync guard — share one source of truth with `isCloudflareModel`.
export function isCloudflareModelId(modelId: string): boolean {
  return modelId.startsWith("@cf/");
}

// Cloudflare Workers AI models (e.g. `@cf/zai-org/glm-5.2`). The gateway serves these over both its
// OpenAI and Anthropic-Messages surfaces (it translates the `@cf/` path), so the Claude adapter can
// drive them just like an Anthropic model. The `@cf/` path prefix is the structural, always-present
// signal, so honour it regardless of `owned_by` — a Cloudflare-served model can report an upstream
// owner (e.g. `@cf/openai/...` with `owned_by: "openai"`) and must still classify as Cloudflare.
export function isCloudflareModel(model: GatewayModel): boolean {
  return isCloudflareModelId(model.id) || model.owned_by === "cloudflare";
}

export interface ModelInfo {
  id: string;
  owned_by?: string;
  allowed: boolean;
  restriction_reason?: string | null;
}

let modelsListCache: ModelsCache<ModelInfo> | null = null;

export async function fetchModelsList(
  options?: FetchGatewayModelsOptions,
): Promise<ModelInfo[]> {
  const gatewayUrl = options?.gatewayUrl ?? process.env.ANTHROPIC_BASE_URL;
  if (!gatewayUrl) {
    return [];
  }

  const token = options?.authToken ?? null;
  const cached = readModelsCache(modelsListCache, gatewayUrl, token);
  if (cached) return cached;

  try {
    const modelsUrl = `${gatewayUrl}/v1/models`;
    const response = await fetch(modelsUrl, {
      headers: authHeaders(options?.authToken),
      signal: AbortSignal.timeout(GATEWAY_FETCH_TIMEOUT_MS),
    });
    if (!response.ok) {
      return [];
    }
    const data = (await response.json()) as ModelsListResponse;
    const models = Array.isArray(data)
      ? data
      : (data.data ?? data.models ?? []);
    const results: ModelInfo[] = [];
    for (const model of models) {
      const id = model?.id ? String(model.id) : "";
      if (!id) continue;
      if (isBlockedModelId(id)) continue;
      results.push({
        id,
        owned_by: model?.owned_by,
        allowed: model?.allowed !== false,
        restriction_reason: model?.restriction_reason ?? null,
      });
    }
    modelsListCache = {
      models: results,
      expiry: Date.now() + CACHE_TTL,
      url: gatewayUrl,
      token,
    };
    return results;
  } catch {
    return [];
  }
}

/**
 * The model a session should start on: the preferred id when present and
 * allowed, else the newest allowed model — a free-tier org must not default
 * onto a model that 403s its first message. Falls back to the preferred id
 * when the list is empty (fetch failed) or nothing is allowed (all locked —
 * the picker gate communicates that state better than a silent swap).
 */
export function pickAllowedModel(
  models: ReadonlyArray<Pick<GatewayModel, "id" | "allowed">>,
  preferred: string,
): string {
  if (models.length === 0) return preferred;
  const preferredEntry = models.find((m) => m.id === preferred);
  if (!preferredEntry || preferredEntry.allowed) return preferred;
  const allowed = models.filter((m) => m.allowed);
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

// Version embedded in the model id, e.g. "claude-opus-4-8" -> 4008. Ids with no
// recognisable version rank newest. A trailing date suffix is ignored.
export function getClaudeModelRecency(modelId: string): number {
  const match = modelId.toLowerCase().match(/-(\d+)(?:[-.](\d+))?/);
  if (!match) return Number.MAX_SAFE_INTEGER;
  const major = Number(match[1]);
  const minor = match[2] ? Number(match[2]) : 0;
  return major * 1000 + minor;
}

// Families ordered least-capable first. The picker opens upward (side="top")
// from the composer, so items later in this list render nearer the trigger and
// read as the top of the menu — this puts the most-capable family (Fable) on
// top. Unknown families sort after all known ones.
const MODEL_FAMILY_ORDER = ["haiku", "sonnet", "opus", "fable"];

function getModelFamilyRank(modelId: string): number {
  const id = modelId.toLowerCase();
  const index = MODEL_FAMILY_ORDER.findIndex((family) => id.includes(family));
  return index === -1 ? MODEL_FAMILY_ORDER.length : index;
}

// Group by family, then newest version first within each family.
export function compareModelsForPicker(a: string, b: string): number {
  const familyDiff = getModelFamilyRank(a) - getModelFamilyRank(b);
  if (familyDiff !== 0) return familyDiff;
  return getClaudeModelRecency(b) - getClaudeModelRecency(a);
}

const PROVIDER_PREFIXES = ["anthropic/", "openai/", "google-vertex/"];

const KNOWN_ACRONYMS = new Set(["gpt", "glm"]);

// For a known acronym, uppercase it, keep the version attached, and title-case
// any suffix: "gpt-5.6-sol" -> "GPT-5.6 Sol", "glm-5.2" -> "GLM-5.2". Other ids
// stay lowercase to avoid mangling ordinary names (e.g. "llama-3.1-8b").
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

  if (isOpenAIModel(model)) {
    return formatProviderModelName(stripProviderPrefix(model.id));
  }

  return formatModelId(model.id);
}

function stripProviderPrefix(modelId: string): string {
  for (const prefix of PROVIDER_PREFIXES) {
    if (modelId.startsWith(prefix)) {
      return modelId.slice(prefix.length);
    }
  }
  return modelId;
}

export function formatModelId(modelId: string): string {
  let cleanId = modelId;
  for (const prefix of PROVIDER_PREFIXES) {
    if (cleanId.startsWith(prefix)) {
      cleanId = cleanId.slice(prefix.length);
      break;
    }
  }

  cleanId = cleanId.replace(/(\d)-(\d)/g, "$1.$2");

  const words = cleanId.split(/[-_]/).map((word) => {
    if (word.match(/^[0-9.]+$/)) return word;
    return word.charAt(0).toUpperCase() + word.slice(1).toLowerCase();
  });

  return words.join(" ");
}
