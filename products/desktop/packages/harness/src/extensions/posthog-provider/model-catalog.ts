import {
  getSupportedThinkingLevels,
  type ModelThinkingLevel,
} from "@earendil-works/pi-ai";
import type { ModelInfo } from "@earendil-works/pi-coding-agent";
import type { CloudRegion } from "@posthog/shared";
import {
  fetchPosthogGatewayModels,
  type GatewayModel,
  resolveModelConfigsFromGatewayModels,
} from "./models";

export const DEFAULT_PI_MODEL_ID = "gpt-5.6-terra";

const PI_MODEL_LABELS: Record<string, string> = {
  "claude-haiku-4-5": "Claude Haiku 4.5",
  "claude-sonnet-5": "Claude Sonnet 5",
  "claude-fable-5": "Claude Fable 5",
  "claude-opus-5": "Claude Opus 5",
  "gpt-5.6-sol": "GPT-5.6 Sol",
  "gpt-5.6-terra": "GPT-5.6 Terra",
  "gpt-5.6-luna": "GPT-5.6 Luna",
  "@cf/zai-org/glm-5.2": "GLM-5.2",
  "zai-org/glm-5.3": "GLM-5.3",
  "zai-org/glm-5.3-flash": "GLM-5.3 Flash",
  "moonshotai/kimi-k3": "Kimi K3",
};

const HIDDEN_PI_MODEL_IDS = new Set([
  "claude-sonnet-4-5",
  "claude-sonnet-4-6",
  "claude-sonnet-4-7",
  "claude-sonnet-4-8",
  "claude-opus-4-5",
  "claude-opus-4-6",
  "claude-opus-4-7",
  "claude-opus-4-8",
  "gpt-5.2",
  "gpt-5.3-codex",
  "gpt-5.4",
  "gpt-5.5",
  "gpt-5-mini",
]);

export type PiModelCatalogEntry = Omit<
  Pick<ModelInfo, "provider" | "id" | "contextWindow">,
  "provider"
> & {
  provider: "posthog";
  name: string;
  isDefault: boolean;
  thinkingLevels: ModelThinkingLevel[];
};

export function resolvePosthogPiModelCatalog(
  gatewayModels: GatewayModel[],
  region: CloudRegion,
): PiModelCatalogEntry[] {
  return resolveModelConfigsFromGatewayModels(gatewayModels, region)
    .filter((model) => !HIDDEN_PI_MODEL_IDS.has(model.id))
    .map((model) => ({
      provider: "posthog",
      id: model.id,
      name: PI_MODEL_LABELS[model.id] ?? model.name,
      isDefault: model.id === DEFAULT_PI_MODEL_ID,
      contextWindow: model.contextWindow,
      thinkingLevels: getSupportedThinkingLevels({
        ...model,
        api: model.api ?? "anthropic-messages",
        baseUrl: model.baseUrl ?? "",
        provider: "posthog",
      }),
    }));
}

export async function fetchPosthogPiModelCatalog(
  gatewayUrl: string,
  region: CloudRegion,
  apiKey?: string,
  projectId?: number,
): Promise<PiModelCatalogEntry[]> {
  const models =
    process.env.PI_OFFLINE || process.env.HARNESS_STATIC_MODELS
      ? []
      : await fetchPosthogGatewayModels(gatewayUrl, apiKey, projectId);
  return resolvePosthogPiModelCatalog(models, region);
}
