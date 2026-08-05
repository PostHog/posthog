import { useService } from "@posthog/di/react";
import { useEffect, useState } from "react";
import { FEATURE_FLAGS, type FeatureFlags } from "./identifiers";

/**
 * The flag's payload when it evaluates enabled for the current user,
 * undefined otherwise. Payloads are remote data: validate with a Zod schema
 * before use.
 */
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
