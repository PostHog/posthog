import { FileTextIcon } from "@phosphor-icons/react";
import type { DocSchemas } from "@posthog/api-client/docs";
import {
  Badge,
  Button,
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Spinner,
  Text,
} from "@posthog/quill";
import { Link } from "@tanstack/react-router";
import { useCreateDoc } from "../hooks/useDocs";
import { useSpaceHome } from "../hooks/useSpaceHome";

const STATUS_LABELS: Record<DocSchemas.DocStatus, string> = {
  draft: "Draft",
  active: "Active",
  done: "Done",
};

/** The space's docs, as a list. Opening one goes to the editor. */
export function SpaceDocsHome({ channelId }: { channelId: string }) {
  const home = useSpaceHome(channelId);
  const createDoc = useCreateDoc(channelId);

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

  if (docs.length === 0) {
    return (
      <Empty className="flex-1">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <FileTextIcon size={20} />
          </EmptyMedia>
          <EmptyTitle>No docs in this space yet</EmptyTitle>
          <EmptyDescription>
            A doc is where the space writes things down together. Start one and
            everyone here can edit it with you.
          </EmptyDescription>
        </EmptyHeader>
        <EmptyContent>
          <Button
            variant="primary"
            loading={createDoc.isPending}
            disabled={createDoc.isPending}
            onClick={() => createDoc.mutate({ template: "blank" })}
          >
            Start a doc
          </Button>
        </EmptyContent>
      </Empty>
    );
  }

  return (
    <div className="@container min-h-0 flex-1 overflow-y-auto px-4 py-3">
      <div className="mx-auto flex max-w-[46rem] flex-col gap-3">
        <div className="flex items-center justify-between gap-2">
          <Text weight="medium">Docs</Text>
          <Button
            size="sm"
            variant="primary"
            loading={createDoc.isPending}
            disabled={createDoc.isPending}
            onClick={() => createDoc.mutate({ template: "blank" })}
          >
            New doc
          </Button>
        </div>

        <ul className="flex flex-col gap-1">
          {docs.map((doc) => (
            <li key={doc.id}>
              <Link
                to="/spaces/$channelId/docs/$docId"
                params={{ channelId, docId: doc.id }}
                className="flex items-center gap-2 rounded-(--radius-2) px-2 py-2 hover:bg-(--gray-3)"
              >
                <FileTextIcon size={16} className="shrink-0 text-(--gray-11)" />
                <span className="min-w-0 flex-1 truncate">
                  {doc.title || "Untitled"}
                </span>
                <Badge variant="default">{STATUS_LABELS[doc.status]}</Badge>
                <Text size="sm" className="shrink-0 text-(--gray-11)">
                  v{doc.version}
                </Text>
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
