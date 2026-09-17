import { useService } from "@posthog/di/react";
import { useEffect, useState } from "react";
import { FEATURE_FLAGS, type FeatureFlags } from "./identifiers";

export function useFeatureFlagVariant(flagKey: string): string | undefined {
  const flags = useService<FeatureFlags>(FEATURE_FLAGS);
  const [variant, setVariant] = useState(() => flags.getVariant(flagKey));

  useEffect(() => {
    const read = () => setVariant(flags.getVariant(flagKey));
    read();
    return flags.onFlagsLoaded(read);
  }, [flags, flagKey]);

  return variant;
}
