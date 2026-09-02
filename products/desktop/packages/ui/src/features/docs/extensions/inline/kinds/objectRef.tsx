import {
  EvidenceHoverCardLoader,
  useEvidenceUrl,
} from "@posthog/ui/features/editor/components/EvidenceRefChip";
import {
  EVIDENCE_PREVIEW_STALE_TIME,
  evidencePreviewQueryKey,
} from "@posthog/ui/features/editor/evidencePreview";
import { fetchEvidencePreviewTimed } from "@posthog/ui/features/editor/evidencePreviewAnalytics";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { getObjectKind } from "@posthog/ui/utils/objectKinds";
import { DocRefIcon } from "../DocRefIcon";
import type { InlineRefKind, InlineRefState } from "../types";

export interface ObjectRefAttrs {
  kind: string;
  objectId: string;
  label: string;
}

function useObjectRef({
  kind,
  objectId,
  label,
}: ObjectRefAttrs): InlineRefState {
  const meta = getObjectKind(kind);
  const target = { kind, id: objectId };
  // Same key and fetcher as the evidence chip, so a doc and a message that
  // name the same object share one read.
  const { data } = useAuthenticatedQuery(
    evidencePreviewQueryKey(target),
    (client) => fetchEvidencePreviewTimed(client, target, "hover"),
    {
      staleTime: EVIDENCE_PREVIEW_STALE_TIME,
      refetchOnWindowFocus: false,
      retry: 1,
      retryOnMount: false,
    },
  );
  const url = useEvidenceUrl(kind, data?.resolvedId ?? objectId);
  const title = label || data?.title || objectId;

  return {
    label: title,
    mark: <DocRefIcon icon={meta.icon} />,
    card: {
      title,
      render: () => (
        <EvidenceHoverCardLoader target={target} url={url}>
          {title}
        </EvidenceHoverCardLoader>
      ),
    },
    onOpen: url ? () => openExternalUrl(url) : undefined,
  };
}

/**
 * A PostHog object, inline in a doc: an insight, a flag, an experiment, a
 * replay, a support ticket, anything in the object-kind registry.
 */
export const objectRef: InlineRefKind<ObjectRefAttrs> = {
  name: "objectChip",
  attributes: {
    kind: { default: "" },
    objectId: { default: "" },
    label: { default: "" },
  },
  parseTag: "span[data-object-chip]",
  domAttributes: ({ kind, objectId }) => ({
    "data-object-chip": `${kind}:${objectId}`,
  }),
  fallbackLabel: ({ label, objectId }) => label || objectId,
  useRef: useObjectRef,
};
