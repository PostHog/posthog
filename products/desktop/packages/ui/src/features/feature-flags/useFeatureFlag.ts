import { useService } from "@posthog/di/react";
import { useEffect, useState } from "react";
import { isFlagForcedOff } from "./devFlagOverrides";
import { FEATURE_FLAGS, type FeatureFlags } from "./identifiers";

export function useFeatureFlag(flagKey: string, defaultValue = false): boolean {
  const flags = useService<FeatureFlags>(FEATURE_FLAGS);
  // A dev-only kill switch, since a dev default beats both the flag's real
  // value and posthog's override. See devFlagOverrides.
  const [enabled, setEnabled] = useState(
    () =>
      !isFlagForcedOff(flagKey) && (flags.isEnabled(flagKey) || defaultValue),
  );

  useEffect(() => {
    const read = () =>
      !isFlagForcedOff(flagKey) && (flags.isEnabled(flagKey) || defaultValue);
    setEnabled(read());

    return flags.onFlagsLoaded(() => {
      setEnabled(read());
    });
  }, [flags, flagKey, defaultValue]);

  return enabled;
}
