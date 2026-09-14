import {
  canvasArtifactManifestSchema,
  canvasBuildStatusSchema,
  canvasDiagnosticSchema,
} from "@posthog/shared";
import { z } from "zod";

// Client-facing shape of a canvas's build lifecycle (the canvases builds
// endpoint, normalized to camelCase by DashboardsService).

export const canvasBuildRecordSchema = z.object({
  id: z.string(),
  sourceVersionId: z.string(),
  buildStatus: canvasBuildStatusSchema,
  diagnostics: z.array(canvasDiagnosticSchema),
  manifest: canvasArtifactManifestSchema.nullable().default(null),
  artifactUrl: z.string().url().nullable(),
  pinned: z.boolean(),
  createdAt: z.string(),
  finishedAt: z.string().nullable(),
});
export type CanvasBuildRecord = z.infer<typeof canvasBuildRecordSchema>;

export const canvasBuildActionInputSchema = z.object({
  id: z.string(),
  buildId: z.string(),
  action: z.enum(["retry", "pin", "unpin", "cancel"]),
});
export type CanvasBuildActionInput = z.infer<
  typeof canvasBuildActionInputSchema
>;

export function publishedCanvasBuild(
  lifecycle: CanvasBuildLifecycle,
): CanvasBuildRecord | null {
  return (
    lifecycle.builds.find(
      (build) =>
        build.id === lifecycle.publishedBuildId &&
        build.buildStatus === "ready",
    ) ?? null
  );
}

export function historicalCanvasBuild(
  lifecycle: CanvasBuildLifecycle,
  versionId: string,
): CanvasBuildRecord | null {
  return (
    lifecycle.builds.find(
      (build) =>
        build.sourceVersionId === versionId &&
        build.buildStatus === "ready" &&
        !!build.artifactUrl,
    ) ?? null
  );
}

/**
 * The build a grid placement renders: the component's live build when the
 * placement follows the latest version, or the pinned version's own retained
 * artifact. A pin resolves to nothing rather than falling back to the live
 * build — the placement's config was written against the version it names, and
 * retention can sweep an unpinned artifact, so the caller must say the pinned
 * version is unavailable instead of quietly rendering a different widget.
 */
export function placementComponentBuild(
  lifecycle: CanvasBuildLifecycle,
  pinnedVersionId: string | null,
): CanvasBuildRecord | null {
  if (pinnedVersionId) {
    return historicalCanvasBuild(lifecycle, pinnedVersionId);
  }
  return (
    lifecycle.builds.find((build) => build.id === lifecycle.publishedBuildId) ??
    null
  );
}

export const canvasBuildLifecycleSchema = z.object({
  /** The live (last successful, still-eligible) build, null until one completes. */
  publishedBuildId: z.string().nullable(),
  /** The source version the canvas's head points at. */
  currentVersionId: z.string().nullable(),
  /** Most recent builds, newest first. */
  builds: z.array(canvasBuildRecordSchema),
});
export type CanvasBuildLifecycle = z.infer<typeof canvasBuildLifecycleSchema>;

/** True while any build is still queued or running (keep polling). */
export function hasActiveCanvasBuild(lifecycle: CanvasBuildLifecycle): boolean {
  return lifecycle.builds.some(
    (build) =>
      build.buildStatus === "queued" || build.buildStatus === "building",
  );
}

/** The newest finished build, used to surface success/failure diagnostics. */
export function latestFinishedCanvasBuild(
  lifecycle: CanvasBuildLifecycle,
): CanvasBuildRecord | null {
  return (
    lifecycle.builds.find(
      (build) =>
        build.buildStatus === "ready" || build.buildStatus === "failed",
    ) ?? null
  );
}

/**
 * The failed build of the canvas's CURRENT head, if it failed. This is the
 * build whose outcome the author actually cares about — a failed newest
 * publish must surface even when an older (e.g. pinned/published) build is the
 * first finished row in the list, because `latestFinishedCanvasBuild` picks by
 * array position, not version identity.
 */
export function currentHeadBuildFailure(
  lifecycle: CanvasBuildLifecycle,
): CanvasBuildRecord | null {
  if (!lifecycle.currentVersionId) return null;
  const latestAttempt = lifecycle.builds.find(
    (build) => build.sourceVersionId === lifecycle.currentVersionId,
  );
  return latestAttempt?.buildStatus === "failed" ? latestAttempt : null;
}
