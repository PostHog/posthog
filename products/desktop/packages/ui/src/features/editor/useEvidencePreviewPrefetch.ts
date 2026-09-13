import type { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import type { QueryClient } from "@tanstack/react-query";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { useConnectivity } from "../../hooks/useConnectivity";
import type { EvidenceLinkTarget } from "../../utils/evidenceLinks";
import { useOptionalAuthenticatedClient } from "../auth/authClient";
import { AUTH_SCOPED_QUERY_META } from "../auth/useCurrentUser";
import {
  EVIDENCE_PREVIEW_STALE_TIME,
  evidencePreviewQueryKey,
} from "./evidencePreview";
import { fetchEvidencePreviewTimed } from "./evidencePreviewAnalytics";

const SETTLE_TIMEOUT_MS = 2000;
const SETTLE_FALLBACK_MS = 250;

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
  const { isOnline } = useConnectivity();
  const client = useOptionalAuthenticatedClient();
  const queryClient = useQueryClient();
  const kind = target.kind;
  const id = target.id;

  useEffect(() => {
    if (!isOnline || !client || !element) return;

    let cancelSettle: (() => void) | undefined;
    const observer = new IntersectionObserver((entries) => {
      if (!entries.some((entry) => entry.isIntersecting)) return;
      observer.disconnect();
      cancelSettle = whenViewSettles(() => {
        void prefetchEvidencePreview(queryClient, client, { kind, id });
      });
    });
    observer.observe(element);

    return () => {
      observer.disconnect();
      cancelSettle?.();
    };
  }, [isOnline, client, queryClient, element, kind, id]);
}
