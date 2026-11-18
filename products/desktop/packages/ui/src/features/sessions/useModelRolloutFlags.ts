import { useService } from "@posthog/di/react";
import { MODEL_ACCESS_FLAGS } from "@posthog/shared/model-catalog";
import { isFlagForcedOff } from "@posthog/ui/features/feature-flags/devFlagOverrides";
import {
  FEATURE_FLAGS,
  type FeatureFlags,
} from "@posthog/ui/features/feature-flags/identifiers";
import { useCallback, useEffect, useState } from "react";
import type { ModelRolloutFlags } from "./modelOptionFilters";

/**
 * The rollout flags gating individual models, read in one place.
 *
 * Which flags to read comes from the catalog rather than from a list kept here, so a model
 * the catalog stops gating is offered to everyone, and a model it starts gating is read
 * rather than silently treated as unreachable. Dev builds default them on, like pi-harness,
 * so the full catalog shows without a posthog override.
 *
 * Read the same way as `useFeatureFlag`, including the re-read once the flags arrive, so a
 * gated model appears as soon as the answers land instead of on the next mount.
 */
export function useModelRolloutFlags(): ModelRolloutFlags {
  const flags = useService<FeatureFlags>(FEATURE_FLAGS);
  const dev = import.meta.env.DEV;
  // Keyed by flag, so a model's `accessFlag` from the catalog reads straight off this
  // rather than each caller knowing which named boolean belongs to which model.
  const read = useCallback(
    (): ModelRolloutFlags =>
      Object.fromEntries(
        MODEL_ACCESS_FLAGS.map((flag) => [
          flag,
          !isFlagForcedOff(flag) && (flags.isEnabled(flag) || dev),
        ]),
      ),
    [flags],
  );
  const [rollout, setRollout] = useState(read);

  useEffect(() => {
    setRollout(read());
    return flags.onFlagsLoaded(() => setRollout(read()));
  }, [flags, read]);

  return rollout;
}
