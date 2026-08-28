import { resolveServiceOptional } from "@posthog/di/container";
import { EVIDENCE_PREVIEW_EAGER_LOADING_FLAG } from "@posthog/shared";
import { useEffect, useState } from "react";
import { FEATURE_FLAGS, type FeatureFlags } from "./identifiers";

// Optional resolution: the quick-ask panel binds no FEATURE_FLAGS and mounts
// no ServiceProvider, so useService would throw; the flag must read as off.
export function useEvidencePreviewEagerLoading(): boolean {
  const [enabled, setEnabled] = useState(
    () =>
      resolveServiceOptional<FeatureFlags>(FEATURE_FLAGS)?.isEnabled(
        EVIDENCE_PREVIEW_EAGER_LOADING_FLAG,
      ) ?? false,
  );

  useEffect(() => {
    const flags = resolveServiceOptional<FeatureFlags>(FEATURE_FLAGS);
    if (!flags) {
      setEnabled(false);
      return;
    }
    const read = () =>
      setEnabled(flags.isEnabled(EVIDENCE_PREVIEW_EAGER_LOADING_FLAG));
    read();
    return flags.onFlagsLoaded(read);
  }, []);

  return enabled;
}
