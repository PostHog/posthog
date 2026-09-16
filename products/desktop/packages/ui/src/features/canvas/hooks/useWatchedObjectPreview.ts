import type { EvidencePreview } from "@posthog/api-client/evidence-previews";
import type { ContextObject } from "@posthog/core/canvas/contextDocument";
import { parsePostHogObjectUrl } from "@posthog/core/canvas/contextDocument";
import {
  EVIDENCE_PREVIEW_STALE_TIME,
  evidencePreviewQueryKey,
} from "@posthog/ui/features/editor/evidencePreview";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";

/**
 * The live state of a watched object: a flag's rollout, an experiment's
 * status, an error issue's volume. Reads the same preview the evidence chips
 * in agent messages use, so the two never disagree and share one cache.
 */
export function useWatchedObjectPreview(object: ContextObject) {
  const parsed = parsePostHogObjectUrl(object.url);
  const target = parsed ? { kind: parsed.kind, id: parsed.id } : null;
  return useAuthenticatedQuery<EvidencePreview | null>(
    target
      ? evidencePreviewQueryKey(target)
      : (["evidence-preview", "none", object.url] as const),
    (client) =>
      target
        ? client.getEvidencePreview(target.kind, target.id)
        : Promise.resolve(null),
    {
      enabled: target !== null && target.kind !== "link",
      staleTime: EVIDENCE_PREVIEW_STALE_TIME,
      retry: false,
    },
  );
}
