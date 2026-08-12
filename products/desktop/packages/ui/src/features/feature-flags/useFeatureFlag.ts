import { useService } from "@posthog/di/react";
import { useEffect, useState } from "react";
import { FEATURE_FLAGS, type FeatureFlags } from "./identifiers";

export function useFeatureFlag(flagKey: string, defaultValue = false): boolean {
  const flags = useService<FeatureFlags>(FEATURE_FLAGS);
  const [enabled, setEnabled] = useState(
    () => flags.isEnabled(flagKey) || defaultValue,
  );

  useEffect(() => {
    setEnabled(flags.isEnabled(flagKey) || defaultValue);

    return flags.onFlagsLoaded(() => {
      setEnabled(flags.isEnabled(flagKey) || defaultValue);
    });
  }, [flags, flagKey, defaultValue]);

  return enabled;
}
