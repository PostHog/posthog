import type { DocSchemas } from "@posthog/api-client/docs";
import { formatRelativeTimeShort } from "@posthog/shared";
import { DocMark } from "@posthog/ui/primitives/DocMark";
import { Link } from "@tanstack/react-router";
import { plainLine } from "./DocThreadRow";

/**
 * The sections the agent keeps checking, across the space's pages.
 *
 * A hypothesis someone wrote down and asked to be watched is a claim about the
 * space, so it belongs on the context page beside the pages themselves. Each row
 * is the words under watch and the last thing the agent said about them.
 */
export function SpaceWatchList({
  channelId,
  watches,
}: {
  channelId: string;
  watches: DocSchemas.WatchSummary[];
}) {
  if (watches.length === 0) return null;
  return (
    <div className="pt-4">
      <h3 className="mb-1 flex items-center gap-1.5 font-medium text-(--gray-11) text-[12px] uppercase tracking-[0.06em]">
        <DocMark variant="agent" size={11} />
        Watching
      </h3>
      <ul className="-mx-2">
        {watches.map((watch) => (
          <li key={`${watch.doc_id}:${watch.anchor_key}`}>
            <Link
              to="/spaces/$channelId/docs/$docId"
              params={{ channelId, docId: watch.doc_id }}
              search={{ thread: watch.anchor_key }}
              className="group flex w-full cursor-pointer flex-col gap-0.5 rounded-(--radius-2) px-2 py-[7px] text-left transition-colors hover:bg-(--gray-3)"
            >
              <span className="flex items-baseline gap-2">
                <span className="min-w-0 flex-1 truncate text-(--gray-12) text-[14px]">
                  “{watch.anchor_text || "a section"}”
                </span>
                <span className="shrink-0 text-(--gray-9) text-[12px]">
                  {watch.doc_title || "Untitled"}
                </span>
              </span>
              <span className="flex items-baseline gap-2 text-[12.5px]">
                <span className="min-w-0 flex-1 truncate text-(--gray-10)">
                  {watch.last_report
                    ? plainLine(watch.last_report)
                    : "Waiting for the first report."}
                </span>
                <span className="w-14 shrink-0 text-right text-(--gray-9) text-[12px] tabular-nums">
                  {watch.last_report_at
                    ? formatRelativeTimeShort(watch.last_report_at)
                    : ""}
                </span>
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
