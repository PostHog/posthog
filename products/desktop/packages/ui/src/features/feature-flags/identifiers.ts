/**
 * Renderer feature-flag access. Desktop adapter wraps the host analytics/
 * posthog-js feature flags; resolved via useService so packages/ui stays
 * host-agnostic.
 */
export interface FeatureFlags {
  isEnabled(flagKey: string): boolean;
  onFlagsLoaded(handler: () => void): () => void;
}

export const FEATURE_FLAGS = Symbol.for("posthog.ui.featureFlags");
