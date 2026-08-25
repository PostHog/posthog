import {
  type GatewayModel,
  normalizeGatewayModelsResponse,
} from "@posthog/shared";
import { buildPosthogProjectHeaderRecord } from "@posthog/shared/posthog-property-headers";

export {
  BLOCKED_GATEWAY_MODEL_IDS,
  buildCloudTaskConfigOptions,
  type CloudTaskConfigOption,
  type CloudTaskConfigSelectOption,
  compareModelsForPicker,
  DEFAULT_CODEX_MODEL,
  DEFAULT_GATEWAY_MODEL,
  formatGatewayModelName,
  formatModelId,
  type GatewayModel,
  getClaudeModelRecency,
  getProviderName,
  isAnthropicModel,
  isBasetenModel,
  isBlockedModelId,
  isCloudflareModel,
  isCloudflareModelId,
  isDeepseekModelId,
  isModalModel,
  isModalModelId,
  isOpenAIModel,
  pickAllowedModel,
} from "@posthog/shared";

export interface FetchGatewayModelsOptions {
  gatewayUrl: string;
  /** Bearer token; required for accurate free-tier marks. */
  authToken?: string;
  projectId?: number;
}

const CACHE_TTL = 10 * 60 * 1000; // 10 minutes

// Bound the gateway /v1/models request so a stalled connection cannot hold up
// session init: this fetch runs inside the Promise.all that gates the 30s SDK
// initialization timeout, so it must resolve well within that window. On abort
// the callers fall through to `return []`.
const GATEWAY_FETCH_TIMEOUT_MS = 10_000;

// Restriction marks are identity-scoped (free-tier marks are authed-only and
// differ per org), so cache entries are keyed on the exact token — an org
// switch in the same process must never be served the old org's marks. A
// token rotation just costs one refetch.
interface ModelsCache<T> {
  models: T[];
  expiry: number;
  url: string;
  token: string | null;
  projectId: number | null;
}

function readModelsCache<T>(
  cache: ModelsCache<T> | null,
  url: string,
  token: string | null,
  projectId: number | null,
): T[] | null {
  if (
    !cache ||
    cache.url !== url ||
    cache.token !== token ||
    cache.projectId !== projectId
  )
    return null;
  return Date.now() < cache.expiry ? cache.models : null;
}

function authHeaders(
  authToken?: string,
  projectId?: number,
): Record<string, string> | undefined {
  if (!authToken && !projectId) return undefined;
  return {
    ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
    ...buildPosthogProjectHeaderRecord(projectId),
  };
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
  const projectId = options?.projectId ?? null;
  const cached = readModelsCache(
    gatewayModelsCache,
    gatewayUrl,
    token,
    projectId,
  );
  if (cached) return cached;

  const modelsUrl = `${gatewayUrl}/v1/models`;

  try {
    const response = await fetch(modelsUrl, {
      headers: authHeaders(options?.authToken, options?.projectId),
      signal: AbortSignal.timeout(GATEWAY_FETCH_TIMEOUT_MS),
    });

    if (!response.ok) {
      return [];
    }

    const models = normalizeGatewayModelsResponse(await response.json());
    gatewayModelsCache = {
      models,
      expiry: Date.now() + CACHE_TTL,
      url: gatewayUrl,
      token,
      projectId,
    };
    return models;
  } catch {
    return [];
  }
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
  const projectId = options?.projectId ?? null;
  const cached = readModelsCache(modelsListCache, gatewayUrl, token, projectId);
  if (cached) return cached;

  try {
    const modelsUrl = `${gatewayUrl}/v1/models`;
    const response = await fetch(modelsUrl, {
      headers: authHeaders(options?.authToken, options?.projectId),
      signal: AbortSignal.timeout(GATEWAY_FETCH_TIMEOUT_MS),
    });
    if (!response.ok) {
      return [];
    }
    const results = normalizeGatewayModelsResponse(await response.json()).map(
      (model) => ({
        id: model.id,
        owned_by: model.owned_by || undefined,
        allowed: model.allowed,
        restriction_reason: model.restriction_reason,
      }),
    );
    modelsListCache = {
      models: results,
      expiry: Date.now() + CACHE_TTL,
      url: gatewayUrl,
      token,
      projectId,
    };
    return results;
  } catch {
    return [];
  }
}
