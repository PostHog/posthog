/**
 * Renderer feature-flag access. Desktop adapter wraps the host analytics/
 * posthog-js feature flags; resolved via useService so packages/ui stays
 * host-agnostic.
 */
export interface FeatureFlags {
  isEnabled(flagKey: string): boolean;
  /**
   * Remote JSON payload attached to a matched flag; undefined when the flag
   * is unmatched or flags haven't loaded. Validate with Zod at the
   * consumption boundary — the shape is whatever was typed into PostHog.
   */
  getPayload(flagKey: string): unknown;
  /**
   * Matched variant of a multivariate flag, or undefined when the flag is
   * unmatched or flags haven't loaded. `isEnabled` cannot distinguish variants
   * — every non-empty variant string is truthy, so a `control` user reads as
   * enabled. Callers comparing against a specific variant must use this.
   */
  getVariant(flagKey: string): string | undefined;
  onFlagsLoaded(handler: () => void): () => void;
}

export const FEATURE_FLAGS = Symbol.for("posthog.ui.featureFlags");
