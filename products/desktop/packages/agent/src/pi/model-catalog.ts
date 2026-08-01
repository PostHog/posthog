import {
  getSupportedThinkingLevels,
  type ModelThinkingLevel,
} from "@earendil-works/pi-ai";
import {
  fetchPosthogGatewayModels,
  type GatewayModel,
  resolveModelConfigsFromGatewayModels,
} from "@posthog/harness/extensions/posthog-provider/models";
import type { CloudRegion } from "@posthog/shared";

export interface PiModelCatalogEntry {
  provider: "posthog";
  id: string;
  name: string;
  contextWindow: number;
  thinkingLevels: ModelThinkingLevel[];
}

export function resolvePosthogPiModelCatalog(
  gatewayModels: GatewayModel[],
  region: CloudRegion,
): PiModelCatalogEntry[] {
  return resolveModelConfigsFromGatewayModels(gatewayModels, region).map(
    (model) => ({
      provider: "posthog",
      id: model.id,
      name: model.name,
      contextWindow: model.contextWindow,
      thinkingLevels: getSupportedThinkingLevels({
        ...model,
        api: model.api ?? "anthropic-messages",
        baseUrl: model.baseUrl ?? "",
        provider: "posthog",
      }),
    }),
  );
}

export async function fetchPosthogPiModelCatalog(
  gatewayUrl: string,
  region: CloudRegion,
  apiKey?: string,
): Promise<PiModelCatalogEntry[]> {
  const models =
    process.env.PI_OFFLINE || process.env.HARNESS_STATIC_MODELS
      ? []
      : await fetchPosthogGatewayModels(gatewayUrl, apiKey);
  return resolvePosthogPiModelCatalog(models, region);
}
