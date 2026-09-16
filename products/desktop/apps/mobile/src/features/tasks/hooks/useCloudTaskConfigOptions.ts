import {
  type Adapter,
  buildCloudTaskConfigOptions,
  buildProviderModelGroups,
  type CloudTaskConfigOption,
  type CloudTaskConfigSelectGroup,
  DEEPSEEK_MODEL_FLAG,
  type GatewayModel,
  GLM_MODEL_FLAG,
  GLM53_FLASH_MODEL_FLAG,
  GLM53_MODEL_FLAG,
  isDeepseekModelId,
  isGlm53FlashModelId,
  isGlm53ModelId,
  isGlmModelId,
  isModalModelId,
  isRestrictedModelOption,
  KIMI_MODEL_FLAG,
} from "@posthog/shared";
import { useQuery } from "@tanstack/react-query";
import { useFeatureFlag } from "posthog-react-native";
import { useMemo } from "react";
import { useAuthStore } from "@/features/auth";
import { getPostHogApiClient } from "@/lib/posthogApiClient";

export const cloudTaskConfigOptionKeys = {
  all: ["cloud-task-config-options"] as const,
  models: () => [...cloudTaskConfigOptionKeys.all, "models"] as const,
};

const emptyModels: GatewayModel[] = [];

export function useCloudTaskConfigOptions(
  adapter: Adapter = "claude",
  currentValue?: string,
) {
  const oauthAccessToken = useAuthStore((state) => state.oauthAccessToken);
  const glmEnabled = useFeatureFlag(GLM_MODEL_FLAG);
  const glm53Enabled = useFeatureFlag(GLM53_MODEL_FLAG);
  const glm53FlashEnabled = useFeatureFlag(GLM53_FLASH_MODEL_FLAG);
  const deepseekEnabled = useFeatureFlag(DEEPSEEK_MODEL_FLAG);
  const kimiEnabled = useFeatureFlag(KIMI_MODEL_FLAG);
  const query = useQuery({
    queryKey: cloudTaskConfigOptionKeys.models(),
    queryFn: () => getPostHogApiClient().getCloudTaskGatewayModels(),
    enabled: !!oauthAccessToken,
    staleTime: 5 * 60 * 1000,
  });
  const models = query.data ?? emptyModels;
  const hasLiveConfig = query.data !== undefined;

  const visibleModels = useMemo(
    () =>
      models.filter(
        (model) =>
          !(!glm53Enabled && isGlm53ModelId(model.id)) &&
          !(!glm53FlashEnabled && isGlm53FlashModelId(model.id)) &&
          !(
            !glmEnabled &&
            isGlmModelId(model.id) &&
            !isGlm53ModelId(model.id) &&
            !isGlm53FlashModelId(model.id)
          ) &&
          !(!deepseekEnabled && isDeepseekModelId(model.id)) &&
          !(!kimiEnabled && isModalModelId(model.id)),
      ),
    [
      models,
      glmEnabled,
      glm53Enabled,
      glm53FlashEnabled,
      deepseekEnabled,
      kimiEnabled,
    ],
  );

  const configOptions = useMemo(
    () =>
      buildCloudTaskConfigOptions(visibleModels, adapter).map((option) => {
        if (option.category !== "model") return option;
        const nextCurrent = option.options.some(
          (model) =>
            model.value === option.currentValue &&
            !isRestrictedModelOption(model._meta),
        )
          ? option.currentValue
          : (option.options.find(
              (model) => !isRestrictedModelOption(model._meta),
            )?.value ?? option.currentValue);
        return { ...option, currentValue: nextCurrent };
      }),
    [visibleModels, adapter],
  );

  const baseModelGroups = useMemo(
    () => buildProviderModelGroups(visibleModels, adapter),
    [visibleModels, adapter],
  );

  // Only rebuild with the synthetic current-value entry when the pick is
  // absent from the catalog. A same-catalog model change reuses baseModelGroups.
  const modelGroups = useMemo(() => {
    if (!currentValue) return baseModelGroups;
    const present = baseModelGroups.some((group) =>
      group.options.some((option) => option.value === currentValue),
    );
    if (present) return baseModelGroups;
    return buildProviderModelGroups(visibleModels, adapter, currentValue);
  }, [baseModelGroups, visibleModels, adapter, currentValue]);

  return {
    ...query,
    configOptions: configOptions as readonly CloudTaskConfigOption[],
    modelGroups: modelGroups as readonly CloudTaskConfigSelectGroup[],
    hasLiveConfig,
    isConfigReady:
      !oauthAccessToken || query.data !== undefined || query.isError,
  };
}
