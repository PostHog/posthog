import type { CanvasBuildRecord } from "@posthog/core/canvas/canvasBuildSchemas";
import type { CanvasArtifactManifest } from "@posthog/shared";
import type { BuiltCanvasFragments } from "./BuiltCanvas";

/** The part of a build the roll-forward decision reads. */
export interface FragmentLayoutIdentity {
  id: string;
  layoutHash: string | undefined;
}

// How many pending fragment paths the build status lists before "+K more".
export const MAX_LISTED_PENDING_FRAGMENTS = 5;

/**
 * Whether the mounted build's frame should stay up and take `latest`'s
 * fragment chunks instead of remounting on `latest`. True only when the flag
 * is on, the builds differ, and both carry the same layoutHash: an equal hash
 * means the layout chunk is byte-identical, so the running document can host
 * the newer fragments. Anything else is today's behavior: remount per build.
 */
export function shouldRollForwardFragments(
  mounted: FragmentLayoutIdentity | null,
  latest: FragmentLayoutIdentity | null,
  flagOn: boolean,
): boolean {
  if (!flagOn || !mounted || !latest) return false;
  if (mounted.id === latest.id) return false;
  if (!mounted.layoutHash || !latest.layoutHash) return false;
  return mounted.layoutHash === latest.layoutHash;
}

/**
 * The artifact directory a build's relative asset paths resolve against: the
 * entry HTML's URL with the entry path removed, and a trailing slash so
 * `new URL("fragments/x.js", base)` lands inside the directory.
 */
export function canvasArtifactBase(
  artifactUrl: string,
  entryHtml: string,
): string {
  const url = new URL(artifactUrl);
  const entry = entryHtml.replace(/^\/+/, "");
  const pathname = url.pathname.endsWith(`/${entry}`)
    ? url.pathname.slice(0, -entry.length)
    : url.pathname.slice(0, url.pathname.lastIndexOf("/") + 1);
  url.pathname = pathname;
  url.search = "";
  url.hash = "";
  return url.href;
}

/** The `set-fragments` payload for a build, or undefined when the build has
 * no artifact URL or was not built with fragments. */
export function fragmentsForBuild(
  build: CanvasBuildRecord,
): BuiltCanvasFragments | undefined {
  const manifest = build.manifest;
  if (!build.artifactUrl || !manifest?.fragments || !manifest.layoutHash) {
    return undefined;
  }
  const base = canvasArtifactBase(build.artifactUrl, manifest.entryHtml);
  return {
    base,
    fragments: manifest.fragments,
    platformCss: manifest.platformCss
      ? new URL(manifest.platformCss, base).href
      : undefined,
  };
}

export interface FragmentProgress {
  ready: number;
  total: number;
  pending: string[];
}

/** Marker progress for the build status, or null when the build has no
 * markers (built without fragments, or a layout that uses none). */
export function fragmentProgress(
  manifest: CanvasArtifactManifest | null | undefined,
): FragmentProgress | null {
  const markers = manifest?.markers;
  if (!markers || markers.length === 0) return null;
  const pending = manifest.pendingFragments ?? [];
  return {
    ready: Math.max(0, markers.length - pending.length),
    total: markers.length,
    pending,
  };
}

/** Pending paths for a compact list: the first few, then "+K more". */
export function formatPendingFragments(
  pending: string[],
  max: number = MAX_LISTED_PENDING_FRAGMENTS,
): string[] {
  if (pending.length <= max) return pending;
  return [...pending.slice(0, max), `+${pending.length - max} more`];
}
