import { CaretRightIcon, ClockIcon } from "@phosphor-icons/react";
import type { ScoutScratchpadEntry } from "@posthog/api-client/posthog-client";
import { splitScratchpadKey } from "@posthog/core/scouts/scoutScratchpad";
import { Badge } from "@posthog/quill";
import { MarkdownRenderer } from "@posthog/ui/features/editor/components/MarkdownRenderer";
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";

// The key prefix (everything before the first colon) encodes the note's *kind* —
// what the scout was doing when it wrote it. Surface it as a colored tag so the
// list scans at a glance.

const KIND_TAG_VARIANT: Record<
  string,
  "info" | "default" | "success" | "warning"
> = {
  pattern: "info",
  dedupe: "default",
  noise: "default",
  baseline: "success",
  watch: "warning",
  watchlist: "warning",
  coverage: "info",
  emerging: "info",
  explore: "info",
  tags: "info",
  recheck: "warning",
};

/**
 * One scratchpad note the scout fleet has written about this project. Shares the
 * collapse/expand grammar of the scout emission cards: a header (chevron · kind ·
 * key · updated time) that stays visible, a 2-line markdown preview when
 * collapsed, the full body plus an attribution footer when open.
 */
export function ScratchpadEntryCard({
  entry,
  expanded,
  onExpandedChange,
}: {
  entry: ScoutScratchpadEntry;
  expanded: boolean;
  onExpandedChange: (expanded: boolean) => void;
}) {
  const { kind, body } = splitScratchpadKey(entry.key);

  return (
    <div className="min-w-0 overflow-hidden rounded-(--radius-2) border border-(--gray-6) bg-gray-1">
      <button
        type="button"
        onClick={() => onExpandedChange(!expanded)}
        aria-expanded={expanded}
        className="flex w-full select-none items-center gap-2 px-3 py-2 text-left"
      >
        <CaretRightIcon
          size={11}
          className={`shrink-0 text-gray-9 transition-transform duration-150 ${expanded ? "rotate-90" : ""}`}
        />
        {kind ? (
          <Badge
            variant={KIND_TAG_VARIANT[kind] ?? "default"}
            className="shrink-0 text-[11px]"
          >
            {kind}
          </Badge>
        ) : null}
        <span className="truncate font-mono text-[12px] text-gray-12">
          {body}
        </span>
        <span className="flex-1" />
        {entry.updated_at ? (
          <div className="flex shrink-0 items-center gap-1 text-gray-10">
            <ClockIcon size={11} className="text-gray-9" />
            <RelativeTimestamp timestamp={entry.updated_at} />
          </div>
        ) : null}
      </button>

      <div className="px-3 pb-2 pl-9">
        <div
          className={`text-pretty break-words text-[12.5px] text-gray-11 leading-relaxed [&_code]:text-[11px] [&_p:last-child]:mb-0 [&_p]:mb-1 [&_pre]:text-[11px] ${
            expanded ? "max-h-72 overflow-y-auto pr-2" : "line-clamp-2"
          }`}
        >
          <MarkdownRenderer content={entry.content || "_No content._"} />
        </div>

        {expanded && entry.created_at ? (
          <div className="mt-2 flex flex-wrap items-center gap-2 border-t border-t-(--gray-5) pt-2 text-[11px] text-gray-10">
            <span className="text-[11px] text-gray-10">Created</span>
            <RelativeTimestamp timestamp={entry.created_at} />
          </div>
        ) : null}
      </div>
    </div>
  );
}
