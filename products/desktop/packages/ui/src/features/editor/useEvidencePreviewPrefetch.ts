import type { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import type { QueryClient } from "@tanstack/react-query";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { useConnectivity } from "../../hooks/useConnectivity";
import type { EvidenceLinkTarget } from "../../utils/evidenceLinks";
import { useOptionalAuthenticatedClient } from "../auth/authClient";
import { AUTH_SCOPED_QUERY_META } from "../auth/useCurrentUser";
import { useEvidencePreviewEagerLoading } from "../feature-flags/useEvidencePreviewEagerLoading";
import {
  EVIDENCE_PREVIEW_STALE_TIME,
  evidencePreviewQueryKey,
} from "./evidencePreview";
import { fetchEvidencePreviewTimed } from "./evidencePreviewAnalytics";

/**
 * Viewport-driven background loading of an evidence (insight link) preview.
 *
 * The hover card fetches only while open; with eager loading enabled this
 * hook watches the chip element and starts the same lookup as soon as the
 * link scrolls into the viewport, so opening the card usually finds the
 * preview already in the react-query cache. The fetch is deliberately
 * deferred: it fires from an idle callback (setTimeout fallback), so a
 * transcript full of references never fires queries while the surrounding
 * view is still rendering or streaming.
 *
 * Safety rails: gated by EVIDENCE_PREVIEW_EAGER_LOADING_FLAG, no-op without
 * an authenticated client or while offline, at most one prefetch per mount,
 * and a fresh cache hit skips the fetch. prefetchQuery swallows fetch
 * errors, so a failed background load surfaces only as the card's static
 * fallback on hover.
 */

/** ms the idle wait can absorb before prefetching anyway. */
const SETTLE_TIMEOUT_MS = 2000;
/** Fallback delay for environments without requestIdleCallback. */
const SETTLE_FALLBACK_MS = 250;

/** Run `callback` once the surrounding view is idle; returns a canceler. */
export function whenViewSettles(
  callback: () => void,
  timeoutMs = SETTLE_TIMEOUT_MS,
): () => void {
  if (typeof requestIdleCallback === "function") {
    const handle = requestIdleCallback(callback, { timeout: timeoutMs });
    return () => {
      if (typeof cancelIdleCallback === "function") {
        cancelIdleCallback(handle);
      }
    };
  }
  const timer = setTimeout(callback, SETTLE_FALLBACK_MS);
  return () => clearTimeout(timer);
}

export function prefetchEvidencePreview(
  queryClient: QueryClient,
  client: PostHogAPIClient,
  target: EvidenceLinkTarget,
): Promise<void> | undefined {
  const queryKey = evidencePreviewQueryKey(target);
  const state = queryClient.getQueryState(queryKey);
  const fresh =
    state?.dataUpdatedAt !== undefined &&
    state.dataUpdatedAt > 0 &&
    Date.now() - state.dataUpdatedAt < EVIDENCE_PREVIEW_STALE_TIME;
  if (fresh) return undefined;
  return queryClient.prefetchQuery({
    queryKey,
    queryFn: () => fetchEvidencePreviewTimed(client, target, "prefetch"),
    staleTime: EVIDENCE_PREVIEW_STALE_TIME,
    meta: AUTH_SCOPED_QUERY_META,
  });
}

export function useEvidencePreviewPrefetch(
  target: EvidenceLinkTarget,
  element: HTMLElement | null,
): void {
  const enabled = useEvidencePreviewEagerLoading();
  const { isOnline } = useConnectivity();
  const client = useOptionalAuthenticatedClient();
  const queryClient = useQueryClient();
  const kind = target.kind;
  const id = target.id;

  useEffect(() => {
    if (!enabled || !isOnline || !client || !element) return;

    let cancelSettle: (() => void) | undefined;
    const observer = new IntersectionObserver(
      (entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) return;
        observer.disconnect();
        cancelSettle = whenViewSettles(() => {
          void prefetchEvidencePreview(queryClient, client, { kind, id });
        });
      },
      // The trigger is the actual viewport entry, not a lead-in margin.
      { rootMargin: "0px" },
    );
    observer.observe(element);

    return () => {
      observer.disconnect();
      cancelSettle?.();
    };
  }, [enabled, isOnline, client, queryClient, element, kind, id]);
}
