import { resolveServiceOptional } from "@posthog/di/container";
import { EVIDENCE_PREVIEW_EAGER_LOADING_FLAG } from "@posthog/shared";
import { useEffect, useState } from "react";
import { FEATURE_FLAGS, type FeatureFlags } from "./identifiers";

/**
 * Eager evidence-link preview loading, gated for staged rollout. When on, a
 * reference chip that scrolls into view prefetches its preview on idle so
 * the hover card opens ready.
 *
 * Reads through the optional root resolver rather than useService: the chip
 * renders in the quick-ask panel, whose container binds no FEATURE_FLAGS
 * (and mounts no ServiceProvider), so eager loading must read as off there
 * instead of throwing.
 */
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
