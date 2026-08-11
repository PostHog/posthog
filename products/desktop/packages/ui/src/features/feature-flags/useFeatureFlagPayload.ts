import { useService } from "@posthog/di/react";
import { useEffect, useState } from "react";
import { FEATURE_FLAGS, type FeatureFlags } from "./identifiers";

export function useFeatureFlagPayload(flagKey: string): unknown {
  const flags = useService<FeatureFlags>(FEATURE_FLAGS);
  const [payload, setPayload] = useState<unknown>(() =>
    flags.getPayload(flagKey),
  );

  useEffect(() => {
    setPayload(flags.getPayload(flagKey));

    return flags.onFlagsLoaded(() => {
      setPayload(flags.getPayload(flagKey));
    });
  }, [flags, flagKey]);

  return payload;
}
