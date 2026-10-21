import {
  type Adapter,
  buildCloudTaskConfigOptions,
  buildProviderModelGroups,
  type CloudTaskConfigOption,
  type CloudTaskConfigSelectGroup,
  type GatewayModel,
  isRestrictedModelOption,
} from "@posthog/shared";
import { useQuery } from "@tanstack/react-query";
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
  const query = useQuery({
    queryKey: cloudTaskConfigOptionKeys.models(),
    queryFn: () => getPostHogApiClient().getCloudTaskGatewayModels(),
    enabled: !!oauthAccessToken,
    staleTime: 5 * 60 * 1000,
  });
  const models = query.data ?? emptyModels;
  const hasLiveConfig = query.data !== undefined;

  // The gateway listing is already scoped to the caller: it drops a model behind a rollout
  // flag the caller does not hold. A second gate here reads flags this app cannot see the
  // catalog for, which is how it hid models the gateway was serving.
  const visibleModels = models;

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
