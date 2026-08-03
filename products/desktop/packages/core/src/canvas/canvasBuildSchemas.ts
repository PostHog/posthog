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
