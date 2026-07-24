import { useService } from "@posthog/di/react";
import { useEffect, useState } from "react";
import { FEATURE_FLAGS, type FeatureFlags } from "./identifiers";

export function useFeatureFlagsLoaded(): boolean {
  const flags = useService<FeatureFlags>(FEATURE_FLAGS);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => flags.onFlagsLoaded(() => setLoaded(true)), [flags]);

  return loaded;
}
