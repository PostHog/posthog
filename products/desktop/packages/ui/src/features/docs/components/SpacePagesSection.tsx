import { FileTextIcon } from "@phosphor-icons/react";
import type { DocSchemas } from "@posthog/api-client/docs";
import { Button, cn, Spinner } from "@posthog/quill";
import { DOCS_FLAG } from "@posthog/shared";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { Link } from "@tanstack/react-router";
import { useCreateDocAndOpen } from "../hooks/useDocs";
import { useSpaceHome } from "../hooks/useSpaceHome";

// Draft is what a page is until someone says otherwise, so it is the absence of
// a mark rather than a word repeated down the whole list.
const STATUS_TONES: Partial<Record<DocSchemas.DocStatus, string>> = {
  active: "text-(--primary)",
  done: "text-(--grass-11)",
};

/** Anything older than this reads better as a date than as an age. */
const MAX_AGE_DAYS = 30;

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
/** The space's context, when it lives in the wiki as a page of its own. */
export interface SpaceContextPageRow {
  /** Where the page sits in the wiki repo. */
  path: string;
  updatedAt?: string;
  onOpen: () => void;
}

export function SpacePagesSection({
  channelId,
  contextPage,
}: {
  channelId: string;
  contextPage?: SpaceContextPageRow;
}) {
  // On in dev builds so the surface is reachable while it is being built; the
  // flag is what turns it on for anyone else.
  const enabled = useFeatureFlag(DOCS_FLAG, import.meta.env.DEV);
  const home = useSpaceHome(channelId);
  const createDoc = useCreateDocAndOpen(channelId);
  const docs = home.data?.docs ?? [];

  if (!enabled) return null;

  const rows = (
    <ul className="pt-2">
      {contextPage ? (
        <li className="border-(--gray-4) border-b last:border-b-0">
          <button
            type="button"
            onClick={contextPage.onOpen}
            className="group -mx-2 flex w-full cursor-pointer items-center gap-2.5 rounded-(--radius-2) px-2 py-2.5 text-left transition-colors hover:bg-(--gray-3)"
          >
            <FileTextIcon
              size={15}
              className="shrink-0 text-(--gray-9) transition-colors group-hover:text-(--gray-11)"
            />
            <span className="min-w-0 flex-1 truncate font-medium text-(--gray-12) text-[14.5px]">
              Context
            </span>
            <span className="w-16 shrink-0 text-right text-(--gray-9) text-[12.5px] tabular-nums">
              {contextPage.updatedAt ? ageLabel(contextPage.updatedAt) : ""}
            </span>
          </button>
        </li>
      ) : null}
      {docs.map((doc) => (
        <li key={doc.id} className="border-(--gray-4) border-b last:border-b-0">
          <Link
            to="/spaces/$channelId/docs/$docId"
            params={{ channelId, docId: doc.id }}
            className="group -mx-2 flex items-center gap-2.5 rounded-(--radius-2) px-2 py-2.5 transition-colors hover:bg-(--gray-3)"
          >
            <FileTextIcon
              size={15}
              className="shrink-0 text-(--gray-9) transition-colors group-hover:text-(--gray-11)"
            />
            <span
              className={cn(
                "min-w-0 flex-1 truncate font-medium text-[14.5px]",
                doc.status === "done" ? "text-(--gray-10)" : "text-(--gray-12)",
              )}
            >
              {doc.title || "Untitled"}
            </span>
            {STATUS_TONES[doc.status] ? (
              <span
                className={cn(
                  "shrink-0 text-[12.5px]",
                  STATUS_TONES[doc.status],
                )}
              >
                {doc.status}
              </span>
            ) : null}
            <span className="w-16 shrink-0 text-right text-(--gray-9) text-[12.5px] tabular-nums">
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
        <div className="flex items-center justify-between gap-3">
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
        ) : docs.length === 0 && !contextPage ? (
          <p className="pt-3 text-(--gray-10) text-sm leading-relaxed">
            No pages yet. A page is where the space writes things down together,
            and everyone here can edit it with you.
          </p>
        ) : (
          rows
        )}
      </div>
    </section>
  );
}
