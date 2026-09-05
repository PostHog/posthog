/**
 * The preview deployment this build targets, when it is a desktop-preview
 * build. Hosts bind a constant value resolved from build-time configuration;
 * `@posthog/core` and `@posthog/ui` read it through this port so they never
 * touch the filesystem, environment, or build constants.
 *
 * The manifest type is the one defined and validated in `@posthog/shared`
 * (`DesktopPreviewManifest`); this package is deliberately dependency-free,
 * so the port carries the structurally identical type declared here. Hosts
 * pass the shared manifest through unchanged.
 */
export interface DesktopPreviewManifest {
  readonly schemaVersion: 1;
  readonly kind: "desktop-preview";
  readonly repository: string;
  readonly prNumber: number;
  readonly commitSha: string;
  readonly backendOrigin: string;
  readonly oauthClientId: string;
  readonly gateway:
    | { readonly kind: "unavailable"; readonly reason: string }
    | { readonly kind: "ai-gateway"; readonly baseUrl: string };
  readonly featureFlags: Readonly<Record<string, boolean>>;
  readonly capabilities: readonly string[];
}

export interface PreviewDeploymentInfo {
  readonly manifest: DesktopPreviewManifest;
  /**
   * Short human-facing label for the preview, e.g. "PR 123 · abc1234".
   * Derived from the validated manifest by the host.
   */
  readonly label: string;
}

export const PREVIEW_DEPLOYMENT = Symbol.for(
  "posthog.platform.previewDeployment",
);
