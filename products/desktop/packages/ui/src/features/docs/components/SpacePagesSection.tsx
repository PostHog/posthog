import { FileTextIcon } from "@phosphor-icons/react";
import type { DocSchemas } from "@posthog/api-client/docs";
import { Button, cn, Spinner } from "@posthog/quill";
import { DOCS_FLAG } from "@posthog/shared";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { DocMark } from "@posthog/ui/primitives/DocMark";
import { Link } from "@tanstack/react-router";
import { useCreateDocAndOpen } from "../hooks/useDocs";
import { useSpaceContextDoc } from "../hooks/useSpaceContextDoc";
import { useSpaceHome } from "../hooks/useSpaceHome";
import { SpaceWatchList } from "./SpaceWatchList";

// Draft is what a page is until someone says otherwise, so it is the absence of
// a mark rather than a word repeated down the whole list.
const STATUS_TONES: Partial<Record<DocSchemas.DocStatus, string>> = {
  active: "text-(--primary)",
  done: "text-(--grass-11)",
};

/** Anything older than this reads better as a date than as an age. */
const MAX_AGE_DAYS = 30;

const ROW_CLASS =
  "group flex w-full cursor-pointer items-center gap-2 rounded-(--radius-2) px-2 py-[7px] text-left transition-colors hover:bg-(--gray-3)";
const ICON_CLASS =
  "shrink-0 text-(--gray-8) transition-colors group-hover:text-(--gray-11)";
const AGE_CLASS =
  "w-14 shrink-0 text-right text-(--gray-9) text-[12px] tabular-nums";

function ageLabel(iso: string): string {
  const then = new Date(iso).getTime();
  if (!Number.isFinite(then)) return "";
  const minutes = Math.floor((Date.now() - then) / 60_000);
  if (minutes < 2) return "now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days <= MAX_AGE_DAYS) return `${days}d ago`;
  return new Date(then).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
}

/**
 * The space's pages, on the space's context page.
 *
 * Context is what a space is: the pages it writes together, the repositories it
 * works in, and the notes an agent reads. The pages lead, because they are the
 * part a person comes here to open.
 *
 * It wears the same shape as the repositories strip beside it: a labelled row
 * with one action, then its contents. A section of its own design would read as
 * something bolted onto the page.
 */
export function SpacePagesSection({ channelId }: { channelId: string }) {
  // On in dev builds so the surface is reachable while it is being built; the
  // flag is what turns it on for anyone else.
  const enabled = useFeatureFlag(DOCS_FLAG, import.meta.env.DEV);
  const home = useSpaceHome(channelId);
  // The notes every agent reads first are a doc too: the one page a space always has.
  const contextDoc = useSpaceContextDoc(channelId);
  const createDoc = useCreateDocAndOpen(channelId);
  const docs = home.data?.docs ?? [];

  if (!enabled) return null;

  const rows = (
    <ul className="-mx-2 pt-1.5">
      {contextDoc.data ? (
        <li>
          <Link
            to="/spaces/$channelId/docs/$docId"
            params={{ channelId, docId: contextDoc.data.id }}
            className={ROW_CLASS}
          >
            <FileTextIcon size={14} className={ICON_CLASS} />
            <span className="truncate font-medium text-(--gray-12) text-[14px]">
              Context
            </span>
            <span className="shrink-0 text-(--gray-9) text-[12px]">
              what every agent reads first
            </span>
            <span className="flex-1" />
            <span className={AGE_CLASS}>
              {ageLabel(contextDoc.data.updated_at)}
            </span>
          </Link>
        </li>
      ) : null}
      {docs.map((doc) => (
        <li key={doc.id}>
          <Link
            to="/spaces/$channelId/docs/$docId"
            params={{ channelId, docId: doc.id }}
            className={cn(ROW_CLASS, "items-start")}
          >
            <FileTextIcon size={14} className={cn(ICON_CLASS, "mt-[3px]")} />
            <span className="min-w-0 flex-1">
              <span className="flex items-baseline gap-2">
                <span
                  className={cn(
                    "min-w-0 truncate font-medium text-[14px]",
                    doc.status === "done"
                      ? "text-(--gray-10)"
                      : "text-(--gray-12)",
                  )}
                >
                  {doc.title || "Untitled"}
                </span>
                {STATUS_TONES[doc.status] ? (
                  <span
                    className={cn(
                      "shrink-0 text-[12px]",
                      STATUS_TONES[doc.status],
                    )}
                  >
                    {doc.status}
                  </span>
                ) : null}
                {/* What lives in the page: open threads and watched sections, as
                    the marks the page itself draws in its margin. */}
                {doc.open_thread_count > 0 || doc.watch_count > 0 ? (
                  <span className="flex shrink-0 items-center gap-2 text-(--gray-9) text-[12px] tabular-nums">
                    {doc.open_thread_count > 0 ? (
                      <span
                        className="flex items-center gap-1"
                        title={`${doc.open_thread_count} open ${doc.open_thread_count === 1 ? "thread" : "threads"}`}
                      >
                        <DocMark variant="discussion" size={10} />
                        {doc.open_thread_count}
                      </span>
                    ) : null}
                    {doc.watch_count > 0 ? (
                      <span
                        className="flex items-center gap-1"
                        title={`${doc.watch_count} watched ${doc.watch_count === 1 ? "section" : "sections"}`}
                      >
                        <DocMark variant="agent" state="working" size={10} />
                        {doc.watch_count}
                      </span>
                    ) : null}
                  </span>
                ) : null}
              </span>
              {doc.excerpt ? (
                <span className="block truncate text-(--gray-10) text-[12.5px]">
                  {doc.excerpt}
                </span>
              ) : null}
            </span>
            <span className={cn(AGE_CLASS, "mt-[2px]")}>
              {ageLabel(doc.updated_at)}
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );

  return (
    <section className="shrink-0">
      <div>
        <div className="flex items-center justify-between gap-3 border-(--gray-4) border-b pb-2.5">
          <h2 className="font-semibold text-(--gray-12) text-[15px] tracking-[-0.008em]">
            Pages
          </h2>
          <Button
            size="sm"
            variant="outline"
            loading={createDoc.isPending}
            disabled={createDoc.isPending}
            onClick={() => createDoc.start("blank")}
          >
            New page
          </Button>
        </div>

        {home.isLoading ? (
          <div className="flex justify-center py-6">
            <Spinner />
          </div>
        ) : home.isError ? (
          <p className="pt-3 text-(--gray-10) text-sm">
            The pages did not load.{" "}
            <button
              type="button"
              className="cursor-pointer underline decoration-(--gray-7) underline-offset-[3px] hover:text-(--gray-12)"
              onClick={() => void home.refetch()}
            >
              Try again
            </button>
          </p>
        ) : docs.length === 0 && !contextDoc.data ? (
          <p className="pt-3 text-(--gray-10) text-sm leading-relaxed">
            No pages yet. A page is where the space writes things down together,
            and everyone here can edit it with you.
          </p>
        ) : (
          rows
        )}
        <SpaceWatchList
          channelId={channelId}
          watches={home.data?.watches ?? []}
        />
      </div>
    </section>
  );
}
