export interface PreviewDeploymentInfo {
  readonly manifest: {
    readonly prNumber: number;
    readonly commitSha: string;
    readonly backendOrigin: string;
  };
  readonly label: string;
}

export const PREVIEW_DEPLOYMENT = Symbol.for(
  "posthog.platform.previewDeployment",
);
