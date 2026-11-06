import { PlayIcon } from "@phosphor-icons/react";
import { Button } from "@posthog/ui/primitives/Button";
import { useAuthenticatedQuery } from "../../../hooks/useAuthenticatedQuery";
import { openExternalUrl } from "../../../shell/openExternal";
import type { ChartBlockSpec } from "../../../utils/chartBlocks";
import { fetchEvidencePreview } from "../evidencePreview";
import { useEvidenceUrl } from "./EvidenceRefChip";

/**
 * Full-size card for `<replay id="..." display="block"/>`: the recording's
 * identity and activity, linking into PostHog's player. Playback stays in
 * PostHog on purpose - the embeddable player requires link sharing, which
 * makes the recording viewable by anyone with the link.
 */
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
      <span className="min-w-0 break-words font-semibold text-[13px] text-gray-12">
        {title}
      </span>
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
      <div className="flex items-center justify-center rounded-(--radius-1) bg-(--gray-a2) py-8">
        <Button
          type="button"
          variant="soft"
          color="gray"
          size="1"
          disabled={!openUrl}
          onClick={() => openUrl && openExternalUrl(openUrl)}
        >
          <PlayIcon size={12} />
          Watch in PostHog
        </Button>
      </div>
      {spec.caption && (
        <figcaption className="m-0 text-[11px] text-gray-10">
          {spec.caption}
        </figcaption>
      )}
    </figure>
  );
}
