import { FileTextIcon } from "@phosphor-icons/react";
import type { DocSchemas } from "@posthog/api-client/docs";
import {
  Button,
  cn,
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Spinner,
} from "@posthog/quill";
import { useTaskChannels } from "@posthog/ui/features/canvas/hooks/useTaskChannels";
import { Link } from "@tanstack/react-router";
import { useCreateDocAndOpen } from "../hooks/useDocs";
import { useSpaceHome } from "../hooks/useSpaceHome";
import { DocTabs } from "./DocTabs";
import "./docs.css";

const STATUS_TONES: Record<DocSchemas.DocStatus, string> = {
  draft: "text-(--gray-11)",
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
 * The space's docs, as the space's front page.
 *
 * It opens with what the space is, then lists every page with its state and how
 * recently it moved, so the row you want is the one you can see.
 */
export function SpaceDocsHome({ channelId }: { channelId: string }) {
  const home = useSpaceHome(channelId);
  const createDoc = useCreateDocAndOpen(channelId);
  const { channels } = useTaskChannels();
  const space = channels.find((channel) => channel.id === channelId);

  if (home.isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <Spinner />
      </div>
    );
  }

  if (home.isError) {
    return (
      <Empty className="flex-1">
        <EmptyHeader>
          <EmptyTitle>The docs in this space did not load</EmptyTitle>
          <EmptyDescription>
            The connection may have dropped. Try again.
          </EmptyDescription>
        </EmptyHeader>
        <EmptyContent>
          <Button variant="primary" onClick={() => void home.refetch()}>
            Try again
          </Button>
        </EmptyContent>
      </Empty>
    );
  }

  const docs = home.data?.docs ?? [];
  const openCount = docs.filter((doc) => doc.status !== "done").length;

  if (docs.length === 0) {
    return (
      <Empty className="flex-1">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <FileTextIcon size={20} />
          </EmptyMedia>
          <EmptyTitle>No pages in this space yet</EmptyTitle>
          <EmptyDescription>
            A page is where the space writes things down together. Start one and
            everyone here can edit it with you.
          </EmptyDescription>
        </EmptyHeader>
        <EmptyContent>
          <Button
            variant="primary"
            loading={createDoc.isPending}
            disabled={createDoc.isPending}
            onClick={() => createDoc.start("blank")}
          >
            Start a page
          </Button>
        </EmptyContent>
      </Empty>
    );
  }

  return (
    <div className="flex h-full min-h-0 min-w-0 flex-1 flex-col">
      <div className="@container min-h-0 flex-1 overflow-y-auto @2xl:px-12 px-5 pt-7 pb-16">
        <div className="mx-auto max-w-[58rem]">
          <h1 className="doc-title text-(--gray-12)">
            {space?.name ? `#${space.name}` : "This space"}
          </h1>
          <p className="mt-2 text-(--gray-11) text-sm">
            The pages this space writes together. Everyone here can edit them,
            and the page you open is live.
          </p>
          <div className="mt-2.5 flex items-center gap-[9px] text-(--gray-9) text-xs">
            <span>
              {docs.length} {docs.length === 1 ? "page" : "pages"}
            </span>
            <span className="size-[3px] rounded-full bg-(--gray-7)" />
            <span>{openCount} not finished</span>
          </div>

          <div className="mt-9 flex items-baseline justify-between gap-2">
            <h2 className="font-semibold text-(--gray-12) text-sm">Pages</h2>
            <button
              type="button"
              className="cursor-pointer text-(--gray-11) text-xs underline decoration-(--gray-7) underline-offset-2 hover:text-(--gray-12)"
              disabled={createDoc.isPending}
              onClick={() => createDoc.start("blank")}
            >
              New page
            </button>
          </div>

          <ul className="mt-1">
            {docs.map((doc) => (
              <li
                key={doc.id}
                className="border-(--gray-4) border-b last:border-0"
              >
                <Link
                  to="/spaces/$channelId/docs/$docId"
                  params={{ channelId, docId: doc.id }}
                  className="flex items-center gap-3 py-2.5 hover:bg-(--gray-2)"
                >
                  <span
                    className={cn(
                      "min-w-0 flex-1 truncate font-medium text-sm",
                      doc.status === "done"
                        ? "text-(--gray-10)"
                        : "text-(--gray-12)",
                    )}
                  >
                    {doc.title || "Untitled"}
                  </span>
                  <span
                    className={cn("shrink-0 text-xs", STATUS_TONES[doc.status])}
                  >
                    {doc.status}
                  </span>
                  <span className="w-16 shrink-0 text-right text-(--gray-9) text-xs">
                    {ageLabel(doc.updated_at)}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      </div>

      <DocTabs
        channelId={channelId}
        docs={docs}
        activeDocId={null}
        creating={createDoc.isPending}
        onCreate={(template) => createDoc.start(template)}
      />
    </div>
  );
}
