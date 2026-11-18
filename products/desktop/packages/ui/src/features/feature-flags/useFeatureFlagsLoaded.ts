import { useService } from "@posthog/di/react";
import { useEffect, useState } from "react";
import { FEATURE_FLAGS, type FeatureFlags } from "./identifiers";

export function useFeatureFlagsLoaded(): boolean {
  const flags = useService<FeatureFlags>(FEATURE_FLAGS);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => flags.onFlagsLoaded(() => setLoaded(true)), [flags]);

  return loaded;
}

export async function resolveFeatureFlagAfterLoad(
  flags: FeatureFlags,
  flagKey: string,
  flagsLoaded: boolean,
): Promise<boolean> {
  if (!flagsLoaded) {
    await new Promise<void>((resolve) => {
      let unsubscribe: (() => void) | undefined;
      let resolvedSynchronously = false;
      const handleLoaded = (): void => {
        resolvedSynchronously = true;
        unsubscribe?.();
        resolve();
      };
      unsubscribe = flags.onFlagsLoaded(handleLoaded);
      if (resolvedSynchronously) {
        unsubscribe();
      }
    });
  }

  return flags.isEnabled(flagKey);
}
