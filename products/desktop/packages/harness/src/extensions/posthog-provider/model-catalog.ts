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

export type PiModelCatalogEntry = Omit<
  Pick<ModelInfo, "provider" | "id" | "contextWindow">,
  "provider"
> & {
  provider: "posthog";
  name: string;
  thinkingLevels: ModelThinkingLevel[];
};

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
