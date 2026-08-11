import {
  type Adapter,
  buildCloudTaskConfigOptions,
  type CloudTaskConfigOption,
  DEEPSEEK_MODEL_FLAG,
  GLM_MODEL_FLAG,
  isDeepseekModelId,
  isGlmModelId,
  isRestrictedModelOption,
} from "@posthog/shared";
import { useQuery } from "@tanstack/react-query";
import { useFeatureFlag } from "posthog-react-native";
import { useAuthStore } from "@/features/auth";
import { getPostHogApiClient } from "@/lib/posthogApiClient";

export const cloudTaskConfigOptionKeys = {
  all: ["cloud-task-config-options"] as const,
  adapter: (adapter: Adapter) =>
    [...cloudTaskConfigOptionKeys.all, adapter] as const,
};

const fallbackOptionsByAdapter: Record<Adapter, CloudTaskConfigOption[]> = {
  claude: buildCloudTaskConfigOptions([], "claude"),
  codex: buildCloudTaskConfigOptions([], "codex"),
};

export function useCloudTaskConfigOptions(adapter: Adapter = "claude") {
  const oauthAccessToken = useAuthStore((state) => state.oauthAccessToken);
  const glmEnabled = useFeatureFlag(GLM_MODEL_FLAG);
  const deepseekEnabled = useFeatureFlag(DEEPSEEK_MODEL_FLAG);
  const query = useQuery({
    queryKey: cloudTaskConfigOptionKeys.adapter(adapter),
    queryFn: () => getPostHogApiClient().getCloudTaskConfigOptions(adapter),
    enabled: !!oauthAccessToken,
    staleTime: 5 * 60 * 1000,
  });
  const configOptions = query.data ?? fallbackOptionsByAdapter[adapter];
  const isHiddenModel = (value: string) =>
    (!glmEnabled && isGlmModelId(value)) ||
    (!deepseekEnabled && isDeepseekModelId(value));
  const visibleConfigOptions =
    glmEnabled && deepseekEnabled
      ? configOptions
      : configOptions.map((option) =>
          option.category === "model"
            ? (() => {
                const options = option.options.filter(
                  (model) => !isHiddenModel(model.value),
                );
                const currentValue = options.some(
                  (model) =>
                    model.value === option.currentValue &&
                    !isRestrictedModelOption(model._meta),
                )
                  ? option.currentValue
                  : (options.find(
                      (model) => !isRestrictedModelOption(model._meta),
                    )?.value ?? option.currentValue);
                return { ...option, currentValue, options };
              })()
            : option,
        );

  return {
    ...query,
    configOptions: visibleConfigOptions,
    hasLiveConfig: query.data !== undefined,
    isConfigReady:
      !oauthAccessToken || query.data !== undefined || query.isError,
  };
}
