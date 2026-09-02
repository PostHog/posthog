import {
  AlertDialog,
  AlertDialogClose,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  Button,
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
  Spinner,
} from "@posthog/quill";
import { useTaskChannels } from "@posthog/ui/features/canvas/hooks/useTaskChannels";
import { useNavigate } from "@tanstack/react-router";
import { useCallback, useRef, useState } from "react";
import type { RemoteCaret } from "../collab/remoteCarets";
import type { DocConnectionStatus } from "../collab/useDocCollab";
import {
  useCreateDocAndOpen,
  useDeleteDoc,
  useDoc,
  useDocs,
  useUpdateDoc,
} from "../hooks/useDocs";
import { DocHeader } from "./DocHeader";
import { DocSurface, type DocSurfaceHandle } from "./DocSurface";
import { DocTabs } from "./DocTabs";
import { DocTitle } from "./DocTitle";

/**
 * One page in a space: the header, the tab row, and the doc surface between them.
 *
 * The surface is keyed on the doc id and on a reload counter, so switching docs
 * or recovering from a lost stream starts a clean editor at the stored version.
 */
export function SpaceDocView({
  channelId,
  docId,
  openThreadKey,
}: {
  channelId: string;
  docId: string;
  /** A thread to open beside the page as it loads, by its anchor key. */
  openThreadKey?: string;
}) {
  const docs = useDocs(channelId);
  const { channels } = useTaskChannels();
  const spaceName = channels.find((channel) => channel.id === channelId)?.name;
  const doc = useDoc(docId);
  const createDoc = useCreateDocAndOpen(channelId);
  const updateDoc = useUpdateDoc(channelId);
  const removeDoc = useDeleteDoc(channelId);
  const navigate = useNavigate();
  const surface = useRef<DocSurfaceHandle>(null);

  /** The page a confirm is open for; deleting a page cannot be undone. */
  const [pendingDelete, setPendingDelete] = useState<{
    id: string;
    title: string;
  } | null>(null);
  const [reloadCount, setReloadCount] = useState(0);
  const [connection, setConnection] =
    useState<DocConnectionStatus>("connecting");
  const [version, setVersion] = useState(0);
  const [peers, setPeers] = useState<RemoteCaret[]>([]);
  const [openThreads, setOpenThreads] = useState(0);

  const onReloadNeeded = useCallback(() => {
    void doc.refetch().then(() => setReloadCount((count) => count + 1));
  }, [doc]);

  if (doc.isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <Spinner />
      </div>
    );
  }

  if (doc.isError || !doc.data) {
    return (
      <Empty className="flex-1">
        <EmptyHeader>
          <EmptyTitle>This doc did not load</EmptyTitle>
          <EmptyDescription>
            It may have been deleted, or the connection dropped. Try again.
          </EmptyDescription>
        </EmptyHeader>
        <EmptyContent>
          <Button variant="primary" onClick={() => void doc.refetch()}>
            Try again
          </Button>
        </EmptyContent>
      </Empty>
    );
  }

  /** Deletes the page, then opens whatever page is left, or the space's pages. */
  const confirmDelete = async () => {
    if (!pendingDelete) return;
    const removedId = pendingDelete.id;
    await removeDoc.mutateAsync(removedId);
    setPendingDelete(null);
    if (removedId !== docId) return;
    const next = (docs.data ?? []).find((entry) => entry.id !== removedId);
    await navigate(
      next
        ? {
            to: "/spaces/$channelId/docs/$docId",
            params: { channelId, docId: next.id },
          }
        : { to: "/spaces/$channelId/context", params: { channelId } },
    );
  };

  return (
    <div className="flex h-full min-h-0 min-w-0 flex-1 flex-col">
      <DocHeader
        spaceName={spaceName ? `#${spaceName}` : "Space"}
        doc={doc.data}
        version={version || doc.data.version}
        connection={connection}
        peers={peers}
        threadCount={openThreads}
        onStatusChange={(status) =>
          updateDoc.mutate({ docId, changes: { status } })
        }
        onOpenThreads={() => surface.current?.toggleThreads()}
        onJumpToPeer={(clientId) => surface.current?.jumpToPeer(clientId)}
        onDelete={
          doc.data.kind === "context"
            ? undefined
            : () =>
                setPendingDelete({
                  id: docId,
                  title: doc.data.title || "Untitled",
                })
        }
      />

      <DocSurface
        ref={surface}
        key={`${docId}:${reloadCount}`}
        doc={doc.data}
        channelId={channelId}
        reloadCount={reloadCount}
        onReloadNeeded={onReloadNeeded}
        openThreadKey={openThreadKey}
        onOpenThreadCount={setOpenThreads}
        onCollabState={(state) => {
          setConnection(state.status);
          setVersion(state.version);
          setPeers(state.peers);
        }}
        lead={
          <DocTitle
            title={doc.data.title}
            peopleCount={peers.length + 1}
            updatedAt={doc.data.updated_at}
            onRename={(title) =>
              updateDoc.mutate({ docId, changes: { title } })
            }
          />
        }
      />

      <DocTabs
        channelId={channelId}
        docs={docs.data ?? []}
        activeDocId={docId}
        creating={createDoc.isPending}
        onCreate={(template) => createDoc.start(template)}
        onDelete={(entry) =>
          setPendingDelete({ id: entry.id, title: entry.title || "Untitled" })
        }
      />

      <AlertDialog
        open={pendingDelete !== null}
        onOpenChange={(open) => {
          if (!open) setPendingDelete(null);
        }}
      >
        <AlertDialogContent className="max-w-md">
          <AlertDialogHeader>
            <AlertDialogTitle>
              Delete {pendingDelete?.title ?? "this page"}?
            </AlertDialogTitle>
            <AlertDialogDescription>
              The page goes for everyone in this space, with everything written
              on it. This cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogClose
              render={<Button variant="outline">Cancel</Button>}
            />
            <Button
              variant="primary"
              loading={removeDoc.isPending}
              disabled={removeDoc.isPending}
              onClick={() => void confirmDelete()}
            >
              Delete page
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

    </div>
  );
}
