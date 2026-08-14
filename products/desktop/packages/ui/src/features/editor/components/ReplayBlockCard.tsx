import { ArrowSquareOutIcon, PlayIcon } from "@phosphor-icons/react";
import { Button } from "@posthog/ui/primitives/Button";
import { useState } from "react";
import { useAuthenticatedQuery } from "../../../hooks/useAuthenticatedQuery";
import { openExternalUrl } from "../../../shell/openExternal";
import type { ChartBlockSpec } from "../../../utils/chartBlocks";
import { useOptionalAuthenticatedClient } from "../../auth/authClient";
import { fetchEvidencePreview } from "../evidencePreview";
import { useEvidenceUrl } from "./EvidenceRefChip";

/**
 * Watchable session replay in agent messages.
 *
 * The player uses PostHog's shared-embed surface, which requires link sharing
 * on the recording. Loading it is always click-driven, and when sharing is
 * off, turning it on is consent-gated: it makes the recording viewable by
 * anyone with the link.
 */

/**
 * The click-driven player area shared by the replay block card and the
 * replay hover card: "Watch here", the consent step when link sharing is
 * off, and the embedded shared player once available.
 */
export function ReplayPlayerArea({ sessionId }: { sessionId: string }) {
  const client = useOptionalAuthenticatedClient();
  const sharing = useAuthenticatedQuery(
    ["replay-embed", sessionId],
    (apiClient) => apiClient.getRecordingEmbedInfo(sessionId),
    { staleTime: 5 * 60 * 1000, refetchOnWindowFocus: false, retry: 1 },
  );

  const [embedUrl, setEmbedUrl] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [enabling, setEnabling] = useState(false);
  const [enableFailed, setEnableFailed] = useState(false);

  const watch = (): void => {
    if (sharing.data?.embedUrl) {
      setEmbedUrl(sharing.data.embedUrl);
      return;
    }
    setConfirming(true);
  };

  const enableAndWatch = async (): Promise<void> => {
    if (!client || enabling) return;
    setEnabling(true);
    setEnableFailed(false);
    try {
      const info = await client.getRecordingEmbedInfo(sessionId, {
        enable: true,
      });
      if (info.embedUrl) {
        setEmbedUrl(info.embedUrl);
        setConfirming(false);
      } else {
        setEnableFailed(true);
      }
    } catch {
      setEnableFailed(true);
    } finally {
      setEnabling(false);
    }
  };

  if (embedUrl) {
    return (
      <iframe
        src={embedUrl}
        title="Session replay player"
        allowFullScreen
        className="aspect-video w-full rounded-(--radius-1) border-0 bg-(--gray-2)"
        data-testid="replay-player"
      />
    );
  }
  if (confirming) {
    return (
      <div className="flex flex-col gap-2 rounded-(--radius-1) bg-(--gray-a2) p-3">
        <span className="text-[12px] text-gray-11">
          Watching in the chat turns on link sharing for this recording. Anyone
          with the link can view it.
        </span>
        {enableFailed && (
          <span className="text-[12px] text-(--red-11)">
            Couldn't turn on sharing. Open the recording in PostHog instead.
          </span>
        )}
        <div className="flex items-center gap-2">
          <Button
            type="button"
            size="1"
            loading={enabling}
            disabled={!client || enabling}
            onClick={() => void enableAndWatch()}
          >
            Enable sharing and watch
          </Button>
          <Button
            type="button"
            variant="soft"
            color="gray"
            size="1"
            disabled={enabling}
            onClick={() => setConfirming(false)}
          >
            Cancel
          </Button>
        </div>
      </div>
    );
  }
  return (
    <div className="flex items-center justify-center rounded-(--radius-1) bg-(--gray-a2) py-8">
      <Button
        type="button"
        variant="soft"
        color="gray"
        size="1"
        disabled={sharing.isPending && !sharing.isError}
        onClick={watch}
      >
        <PlayIcon size={12} />
        Watch here
      </Button>
    </div>
  );
}

export function ReplayBlockCard({
  spec,
}: {
  spec: Extract<ChartBlockSpec, { mode: "replay" }>;
}) {
  const openUrl = useEvidenceUrl("replay", spec.sessionId);

  const metadata = useAuthenticatedQuery(
    ["evidence-preview", "replay", spec.sessionId],
    (apiClient) =>
      fetchEvidencePreview(apiClient, { kind: "replay", id: spec.sessionId }),
    { staleTime: 5 * 60 * 1000, refetchOnWindowFocus: false, retry: 1 },
  );

  const preview = metadata.data ?? null;
  const title = spec.title ?? preview?.title ?? "Session replay";

  return (
    <figure
      className="m-0 mb-2 flex flex-col gap-2 rounded-(--radius-2) border border-(--gray-4) bg-(--color-panel-solid) p-3"
      data-testid="replay-card"
    >
      <div className="flex items-start justify-between gap-2">
        <span className="min-w-0 break-words font-semibold text-[13px] text-gray-12">
          {title}
        </span>
        {openUrl && (
          <Button
            type="button"
            variant="ghost"
            color="gray"
            size="1"
            aria-label="Open in PostHog"
            tooltipContent="Open in PostHog"
            className="shrink-0"
            onClick={() => openExternalUrl(openUrl)}
          >
            <ArrowSquareOutIcon size={13} />
          </Button>
        )}
      </div>
      {(preview?.detail || (preview?.facts?.length ?? 0) > 0) && (
        <div className="flex flex-wrap items-center gap-1.5">
          {preview?.detail && (
            <span className="text-(--gray-10) text-[11.5px]">
              {preview.detail}
            </span>
          )}
          {preview?.facts?.map((fact) => (
            <span
              key={fact}
              className="max-w-full truncate rounded-[4px] bg-(--gray-a3) px-1.5 py-0.5 text-(--gray-11) text-[10px]"
            >
              {fact}
            </span>
          ))}
        </div>
      )}
      <ReplayPlayerArea sessionId={spec.sessionId} />
      {spec.caption && (
        <figcaption className="m-0 text-[11px] text-gray-10">
          {spec.caption}
        </figcaption>
      )}
    </figure>
  );
}
