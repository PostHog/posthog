import type {
  CanvasBuildLifecycle,
  CanvasBuildRecord,
} from "@posthog/core/canvas/canvasBuildSchemas";
import { useHostTRPC } from "@posthog/host-router/react";
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import type { BuiltCanvasFragments } from "./BuiltCanvas";
import {
  fragmentsForBuild,
  shouldRollForwardFragments,
} from "./canvasFragments";

// How long a mounted artifact iframe gets to post "ready"/"rendered" before
// its signed URL is suspected expired.
const ARTIFACT_READY_GRACE_MS = 15_000;
// Signed artifact URLs live ~60 minutes; below this age a load failure is a
// canvas bug, not an expired URL, so no refresh is attempted.
const ARTIFACT_URL_FRESH_MS = 50 * 60_000;

// The published build's artifact, pinned to a single signed URL. Every builds
// refetch mints a fresh URL for the same artifact, so rendering the lifecycle
// value directly would reload the iframe every 2s poll while a build runs.
export interface PinnedArtifact {
  buildId: string;
  url: string;
  /** Epoch ms the pinned URL was minted (the builds fetch that produced it). */
  mintedAt: number;
  /** The refresh nonce the pin was adopted under, so a remount also re-stamps
   * the pin's mint time (otherwise the expiry timer would keep firing on a URL
   * that's already been recovered). */
  refreshKey: number;
  /** The mounted build's layout hash, when it was built with fragments. A
   * newer build with the same hash rolls its fragments into this frame. */
  layoutHash: string | undefined;
}

/** A newer build's fragments held for the mounted frame, pinned to the build
 * (and the signed URLs of the fetch) that produced them. */
interface PinnedFragments {
  buildId: string;
  fragments: BuiltCanvasFragments | undefined;
}

/**
 * The signed-URL lifecycle of a canvas's published artifact: pins the artifact
 * to one URL per build (URL identity ≠ artifact identity — every lifecycle
 * refetch mints a fresh URL for the same bytes), and recovers from an expired
 * pin by refetching the lifecycle and remounting the frame via `refreshKey`.
 * Remounting, not URL-string compare, is what guarantees a wedged iframe
 * actually retries: the token endpoint is the authority, and a new URL for the
 * same bucket would be byte-identical.
 *
 * Callers key the artifact frame on `${artifact.buildId}:${refreshKey}` and
 * wire `onReady` to the frame's ready AND rendered signals — either one proves
 * the pinned URL still loads.
 */
export function usePinnedArtifact({
  dashboardId,
  publishedBuild,
  lifecycle,
  mintedAt,
  suspended,
  rollForwardFragments = false,
}: {
  dashboardId: string;
  publishedBuild: CanvasBuildRecord | null;
  lifecycle: CanvasBuildLifecycle | undefined;
  /** Epoch ms of the builds fetch that produced `publishedBuild`'s URL. */
  mintedAt: number;
  /** True while the artifact frame isn't on screen (e.g. version browsing);
   * pauses the expiry-recovery timer, which can only judge a mounted frame. */
  suspended: boolean;
  /** True when the progressive-fragments flag is on: a newer published build
   * with the mounted build's layoutHash keeps the frame and only hands over
   * its fragments. Off, every new build remounts. */
  rollForwardFragments?: boolean;
}): {
  artifact: PinnedArtifact | null;
  /** The newer build's fragments for the mounted frame, when rolled forward. */
  fragments: BuiltCanvasFragments | undefined;
  /** The build `fragments` came from; the mounted build otherwise. */
  fragmentsBuildId: string | undefined;
  refreshKey: number;
  onReady: () => void;
} {
  const trpc = useHostTRPC();
  const queryClient = useQueryClient();

  // Adopt a fresh pin only when the published build itself changes (or a
  // refresh was requested). Adjusted during render (not an effect) so the swap
  // can't flash a stale frame.
  const [pinnedArtifact, setPinnedArtifact] = useState<PinnedArtifact | null>(
    null,
  );
  // A nonce that, when bumped, remounts the artifact frame so it revalidates
  // against the live token endpoint (ETag/304 makes this cheap) — the recovery
  // path when the pinned URL expired.
  const [refreshKey, setRefreshKey] = useState(0);
  // Kept apart from the pin so adopting fragments doesn't restart the expiry
  // timer below, which is keyed on the pin's identity.
  const [pinnedFragments, setPinnedFragments] =
    useState<PinnedFragments | null>(null);
  if (publishedBuild?.artifactUrl) {
    const rollForward =
      !!pinnedArtifact &&
      pinnedArtifact.refreshKey === refreshKey &&
      shouldRollForwardFragments(
        { id: pinnedArtifact.buildId, layoutHash: pinnedArtifact.layoutHash },
        {
          id: publishedBuild.id,
          layoutHash: publishedBuild.manifest?.layoutHash,
        },
        rollForwardFragments,
      );
    const adoptFresh =
      !rollForward &&
      (!pinnedArtifact ||
        pinnedArtifact.buildId !== publishedBuild.id ||
        pinnedArtifact.refreshKey !== refreshKey);
    if (adoptFresh) {
      setPinnedArtifact({
        buildId: publishedBuild.id,
        url: publishedBuild.artifactUrl,
        mintedAt: mintedAt || Date.now(),
        refreshKey,
        layoutHash: publishedBuild.manifest?.layoutHash,
      });
      if (pinnedFragments) setPinnedFragments(null);
    } else if (rollForward && pinnedFragments?.buildId !== publishedBuild.id) {
      // Adopted once per newer build: every poll mints fresh signed URLs, and
      // re-sending them would make the document re-import unchanged chunks.
      setPinnedFragments({
        buildId: publishedBuild.id,
        fragments: fragmentsForBuild(publishedBuild),
      });
    }
  } else if (lifecycle && pinnedArtifact) {
    // The lifecycle says there's no published build anymore — drop the pin.
    setPinnedArtifact(null);
    setPinnedFragments(null);
  }

  // Expired-URL recovery: if the mounted artifact never posts "ready" or
  // "rendered" within the grace window AND the pinned URL is old enough to
  // have expired, refetch the lifecycle (minting a fresh URL) and adopt it.
  const artifactLoadedRef = useRef(false);
  const onReady = useCallback(() => {
    artifactLoadedRef.current = true;
  }, []);
  const renderedArtifact = !suspended ? pinnedArtifact : null;
  useEffect(() => {
    if (!renderedArtifact) return;
    artifactLoadedRef.current = false;
    const timer = setTimeout(() => {
      if (artifactLoadedRef.current) return;
      if (Date.now() - renderedArtifact.mintedAt < ARTIFACT_URL_FRESH_MS) {
        return;
      }
      // Refetch mints the current bucket's URL (re-checking the token server-
      // side even when the browser would reframe from cache), then remount the
      // frame so it revalidates against those endpoints. The remount, not a URL
      // string change, is what un-wedges a frame whose module fetches hung.
      void queryClient
        .invalidateQueries({
          queryKey: trpc.dashboards.builds.queryKey({ id: dashboardId }),
        })
        .then(() => setRefreshKey((k) => k + 1));
    }, ARTIFACT_READY_GRACE_MS);
    return () => clearTimeout(timer);
  }, [renderedArtifact, dashboardId, queryClient, trpc]);

  return {
    artifact: pinnedArtifact,
    fragments: pinnedFragments?.fragments,
    fragmentsBuildId: pinnedFragments?.buildId ?? pinnedArtifact?.buildId,
    refreshKey,
    onReady,
  };
}
