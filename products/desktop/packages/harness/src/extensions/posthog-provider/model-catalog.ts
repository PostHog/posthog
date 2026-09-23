import {
  getSupportedThinkingLevels,
  type ModelThinkingLevel,
} from "@earendil-works/pi-ai";
import type { ModelInfo } from "@earendil-works/pi-coding-agent";
import {
  type CloudRegion,
  formatGatewayModelName,
  isHiddenPiModelId,
} from "@posthog/shared";
import { labelForModel } from "@posthog/shared/model-catalog";
import {
  fetchPosthogGatewayModels,
  type GatewayModel,
  resolveModelConfigsFromGatewayModels,
} from "./models";

export const DEFAULT_PI_MODEL_ID = "gpt-5.6-terra";

export type PiModelCatalogEntry = Omit<
  Pick<ModelInfo, "provider" | "id" | "contextWindow">,
  "provider"
> & {
  provider: "posthog";
  name: string;
  isDefault: boolean;
  thinkingLevels: ModelThinkingLevel[];
};

// The provider config loses owned_by, so the shared formatter falls back to
// id-based detection. Keeps Pi's names identical to the shared model picker.
function piModelDisplayName(model: { id: string; name: string }): string {
  if (model.name !== model.id) return model.name;
  return formatGatewayModelName({
    id: model.id,
    owned_by: "",
    context_window: 0,
    supports_streaming: false,
    supports_vision: false,
    allowed: true,
  });
}

export function resolvePosthogPiModelCatalog(
  gatewayModels: GatewayModel[],
  region: CloudRegion,
): PiModelCatalogEntry[] {
  return resolveModelConfigsFromGatewayModels(gatewayModels, region)
    .filter((model) => !isHiddenPiModelId(model.id))
    .map((model) => ({
      provider: "posthog",
      id: model.id,
      // Catalog name first, so Pi reads the same as every other picker.
      name: labelForModel(model.id) ?? piModelDisplayName(model),
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
