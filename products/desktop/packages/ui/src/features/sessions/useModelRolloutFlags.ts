import {
  DEEPSEEK_MODEL_FLAG,
  GLM_MODEL_FLAG,
  GLM53_FLASH_MODEL_FLAG,
  GLM53_MODEL_FLAG,
  KIMI_MODEL_FLAG,
} from "@posthog/shared";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { useMemo } from "react";
import type { ModelRolloutFlags } from "./modelOptionFilters";

/**
 * The rollout flags gating individual models, read in one place. Dev builds
 * default them on, like pi-harness, so the full catalog shows without a
 * posthog override. Memoized so the object can sit in dependency arrays.
 */
export function useModelRolloutFlags(): ModelRolloutFlags {
  const dev = import.meta.env.DEV;
  const deepseek = useFeatureFlag(DEEPSEEK_MODEL_FLAG, dev);
  const glm = useFeatureFlag(GLM_MODEL_FLAG, dev);
  const glm53 = useFeatureFlag(GLM53_MODEL_FLAG, dev);
  const glm53Flash = useFeatureFlag(GLM53_FLASH_MODEL_FLAG, dev);
  const kimi = useFeatureFlag(KIMI_MODEL_FLAG, dev);
  // Keyed by flag, so a model's `accessFlag` from the catalog reads straight off this
  // rather than each caller knowing which named boolean belongs to which model.
  return useMemo(
    () => ({
      [DEEPSEEK_MODEL_FLAG]: deepseek,
      [GLM_MODEL_FLAG]: glm,
      [GLM53_MODEL_FLAG]: glm53,
      [GLM53_FLASH_MODEL_FLAG]: glm53Flash,
      [KIMI_MODEL_FLAG]: kimi,
    }),
    [deepseek, glm, glm53, glm53Flash, kimi],
  );
}
