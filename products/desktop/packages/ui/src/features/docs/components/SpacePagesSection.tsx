import { FileTextIcon } from "@phosphor-icons/react";
import type { DocSchemas } from "@posthog/api-client/docs";
import { Button, Spinner } from "@posthog/quill";
import { DOCS_FLAG } from "@posthog/shared";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { DocMark } from "@posthog/ui/primitives/DocMark";
import { useCreateDocAndOpen } from "../hooks/useDocs";
import { useSpaceContextDoc } from "../hooks/useSpaceContextDoc";
import { useSpaceHome } from "../hooks/useSpaceHome";
import { SpaceRow, SpaceSectionHeader } from "./SpaceRow";
import { SpaceWatchList } from "./SpaceWatchList";

/** Anything older than this reads better as a date than as an age. */
const MAX_AGE_DAYS = 30;

function ageLabel(iso: string): string {
  const then = new Date(iso).getTime();
  if (!Number.isFinite(then)) return "";
  const minutes = Math.floor((Date.now() - then) / 60_000);
  if (minutes < 2) return "now";
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h`;
  const days = Math.floor(hours / 24);
  if (days <= MAX_AGE_DAYS) return `${days}d`;
  return new Date(then).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
}

function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

// Draft is what a page is until someone says otherwise, so it is the absence of
// a word rather than one repeated down the whole list.
function docMeta(doc: DocSchemas.DocSummary): string | null {
  const parts: string[] = [];
  if (doc.status === "active" || doc.status === "done") parts.push(doc.status);
  if (doc.open_thread_count > 0) {
    parts.push(plural(doc.open_thread_count, "thread", "threads"));
  }
  if (doc.watch_count > 0) parts.push(`${doc.watch_count} watching`);
  return parts.length > 0 ? parts.join(" · ") : null;
}

/**
 * The space's pages, on the space's context page, then the claims those pages
 * watch. Both lists share one row shape and one header.
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
  const watches = home.data?.watches ?? [];
  const movedDocIds = new Set(
    watches
      .filter((watch) => watch.status === "active" && watch.verdict === "moved")
      .map((watch) => watch.doc_id),
  );

  if (!enabled) return null;

  const rows = (
    <ul className="-mx-2 pt-1.5">
      {contextDoc.data ? (
        <SpaceRow
          icon={<FileTextIcon size={14} />}
          title="Context"
          meta="what every agent reads first"
          age={ageLabel(contextDoc.data.updated_at)}
          link={{
            to: "/spaces/$channelId/docs/$docId",
            params: { channelId, docId: contextDoc.data.id },
          }}
        />
      ) : null}
      {docs.map((doc) => (
        <SpaceRow
          key={doc.id}
          icon={
            movedDocIds.has(doc.id) ? (
              <DocMark variant="agent" state="moved" size={11} />
            ) : (
              <FileTextIcon size={14} />
            )
          }
          title={doc.title || "Untitled"}
          meta={docMeta(doc)}
          age={ageLabel(doc.updated_at)}
          excerpt={doc.excerpt || undefined}
          muted={doc.status === "done"}
          link={{
            to: "/spaces/$channelId/docs/$docId",
            params: { channelId, docId: doc.id },
          }}
        />
      ))}
    </ul>
  );

  return (
    <>
      <section className="shrink-0">
        <SpaceSectionHeader
          title="Pages"
          aside={
            <Button
              size="sm"
              variant="outline"
              loading={createDoc.isPending}
              disabled={createDoc.isPending}
              onClick={() => createDoc.start("blank")}
            >
              New page
            </Button>
          }
        />
        {home.isLoading ? (
          <div className="flex justify-center py-6">
            <Spinner />
          </div>
        ) : home.isError ? (
          <p className="pt-3 text-(--gray-10) text-[12.5px]">
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
          <p className="pt-3 text-(--gray-10) text-[12.5px] leading-relaxed">
            No pages yet. A page is where the space writes things down together,
            and everyone here can edit it with you.
          </p>
        ) : (
          rows
        )}
      </section>
      <SpaceWatchList channelId={channelId} watches={watches} />
    </>
  );
}
