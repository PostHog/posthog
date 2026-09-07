import {
  DesktopPreviewConfigError,
  type DesktopPreviewManifest,
  PREVIEW_DEPLOYMENT_METADATA_PATH,
  previewDeploymentMetadataSchema,
} from "@posthog/shared";

export async function checkPreviewRevision(
  preview: DesktopPreviewManifest,
  fetchImpl: (input: string, init?: RequestInit) => Promise<Response> = fetch,
): Promise<void> {
  const response = await fetchImpl(
    `${preview.backendOrigin}${PREVIEW_DEPLOYMENT_METADATA_PATH}`,
    {
      signal: AbortSignal.timeout(5000),
      cache: "no-store",
      redirect: "error",
    },
  );
  if (!response.ok) {
    throw new DesktopPreviewConfigError(
      "The preview backend is unavailable. Open it in your browser to wake it, then try again.",
    );
  }
  const parsed = previewDeploymentMetadataSchema.safeParse(
    await response.json(),
  );
  if (!parsed.success) {
    throw new DesktopPreviewConfigError(
      "Could not verify the preview backend. Rebuild the preview from its pull request.",
    );
  }
  if (
    parsed.data.prNumber !== preview.prNumber ||
    parsed.data.commitSha !== preview.commitSha
  ) {
    throw new DesktopPreviewConfigError(
      "The preview backend has changed. Download the latest installer from the pull request.",
    );
  }
}
