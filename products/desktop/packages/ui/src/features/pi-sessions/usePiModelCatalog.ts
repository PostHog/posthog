import { useHostTRPC } from "@posthog/host-router/react";
import {
  DEEPSEEK_MODEL_FLAG,
  GLM_MODEL_FLAG,
  GLM53_FLASH_MODEL_FLAG,
  GLM53_MODEL_FLAG,
  getCloudUrlFromRegion,
  KIMI_MODEL_FLAG,
} from "@posthog/shared";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { stripDisabledModels } from "@posthog/ui/features/sessions/modelOptionFilters";
import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

export function usePiModelCatalog(enabled: boolean) {
  const trpc = useHostTRPC();
  const cloudRegion = useAuthStateValue((state) => state.cloudRegion);
  const deepseek = useFeatureFlag(DEEPSEEK_MODEL_FLAG);
  const glm = useFeatureFlag(GLM_MODEL_FLAG);
  const glm53 = useFeatureFlag(GLM53_MODEL_FLAG);
  const glm53Flash = useFeatureFlag(GLM53_FLASH_MODEL_FLAG);
  const kimiEnabled = useFeatureFlag(KIMI_MODEL_FLAG);
  const apiHost = useMemo(
    () => (cloudRegion ? getCloudUrlFromRegion(cloudRegion) : null),
    [cloudRegion],
  );

  return useQuery({
    ...trpc.agent.getPiModelCatalog.queryOptions({
      apiHost: apiHost ?? "",
      region: cloudRegion ?? "us",
    }),
    enabled: enabled && apiHost !== null,
    select: (models) =>
      stripDisabledModels(models, {
        deepseek,
        glm,
        glm53,
        glm53Flash,
        kimi: kimiEnabled,
      }),
  });
}
