import {
  Button,
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
  Spinner,
  Text,
} from "@posthog/quill";
import type { Editor } from "@tiptap/core";
import { useCallback, useEffect, useRef, useState } from "react";
import type { DocConnectionStatus } from "../collab/useDocCollab";
import {
  useDiscussionMutations,
  useDocDiscussions,
} from "../hooks/useDocDiscussions";
import { useCreateDoc, useDoc, useDocs, useUpdateDoc } from "../hooks/useDocs";
import { DiscussionsPanel } from "./DiscussionsPanel";
import { DocAgentThread } from "./DocAgentThread";
import { DocEditor } from "./DocEditor";
import { DocHeader } from "./DocHeader";
import { DocTabs } from "./DocTabs";

/**
 * One doc in a space: the tab row, the body, and the discussions beside it.
 *
 * The editor is keyed on the doc id and on a reload counter, so switching docs
 * or recovering from a lost stream starts a clean editor at the stored version.
 */
export function SpaceDocView({
  channelId,
  docId,
}: {
  channelId: string;
  docId: string;
}) {
  const docs = useDocs(channelId);
  const doc = useDoc(docId);
  const createDoc = useCreateDoc(channelId);
  const updateDoc = useUpdateDoc(channelId);

  const discussions = useDocDiscussions(docId);
  const discussionActions = useDiscussionMutations(docId);

  const [panelOpen, setPanelOpen] = useState(false);
  const [agentTaskId, setAgentTaskId] = useState<string | null>(null);
  const editorRef = useRef<Editor | null>(null);
  const [selectedAnchorKey, setSelectedAnchorKey] = useState<string | null>(
    null,
  );
  const [pendingAnchor, setPendingAnchor] = useState<{
    anchorKey: string;
    anchorText: string;
  } | null>(null);
  const [reloadCount, setReloadCount] = useState(0);
  const [connection, setConnection] =
    useState<DocConnectionStatus>("connecting");
  const [version, setVersion] = useState(0);

  // One id per open editor. Two windows on the same doc must never share it,
  // or each would treat the other's steps as its own.
  const editorKey = `${docId}:${reloadCount}`;
  const clientIdRef = useRef({ key: editorKey, id: crypto.randomUUID() });
  if (clientIdRef.current.key !== editorKey) {
    clientIdRef.current = { key: editorKey, id: crypto.randomUUID() };
  }
  const clientId = clientIdRef.current.id;

  const bodyRef = useRef<HTMLDivElement>(null);

  const onReloadNeeded = useCallback(() => {
    void doc.refetch().then(() => setReloadCount((count) => count + 1));
  }, [doc]);

  const onDiscussionStarted = useCallback(
    (anchor: { anchorKey: string; anchorText: string }) => {
      setPendingAnchor(anchor);
      setSelectedAnchorKey(anchor.anchorKey);
      setAgentTaskId(null);
      setPanelOpen(true);
    },
    [],
  );

  const openAgentThread = useCallback((taskId: string) => {
    setAgentTaskId(taskId);
    setPanelOpen(true);
  }, []);

  // The only path from an agent answer into the page. The text lands where the
  // caret is and stays selected, so it is obvious what arrived.
  const addAgentAnswerToPage = useCallback((text: string) => {
    editorRef.current?.chain().focus().insertContent(`\n${text}\n`).run();
  }, []);

  // A click on a marked phrase opens its thread. The mark carries the key, so
  // nothing has to track positions. The listener sits on the body element
  // rather than on a React prop: the marks are rendered by the editor, not by
  // this component.
  useEffect(() => {
    const body = bodyRef.current;
    if (!body) return;
    const onClick = (event: MouseEvent) => {
      const target = event.target as HTMLElement | null;
      const key = target
        ?.closest("[data-anchor-key]")
        ?.getAttribute("data-anchor-key");
      if (!key) return;
      setSelectedAnchorKey(key);
      setPanelOpen(true);
    };
    body.addEventListener("click", onClick);
    return () => body.removeEventListener("click", onClick);
  }, []);

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

  const threads = discussions.data ?? [];

  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col">
      <div className="flex min-w-0 items-center gap-2 border-(--gray-5) border-b px-4 py-2">
        <DocTabs
          channelId={channelId}
          docs={docs.data ?? []}
          activeDocId={docId}
          creating={createDoc.isPending}
          onCreate={(template) => createDoc.mutate({ template })}
        />
      </div>

      <DocHeader
        doc={doc.data}
        version={version || doc.data.version}
        connection={connection}
        discussionCount={threads.filter((thread) => !thread.resolved).length}
        onRename={(title) => updateDoc.mutate({ docId, changes: { title } })}
        onStatusChange={(status) =>
          updateDoc.mutate({ docId, changes: { status } })
        }
        onOpenDiscussions={() => {
          setAgentTaskId(null);
          setPanelOpen((open) => !open);
        }}
      />

      {/* A side panel needs room. Below the container breakpoint it covers the
          doc instead of squeezing it, which keeps the text readable in a narrow
          window beside the rail and another panel. */}
      <div className="@container relative flex min-h-0 flex-1">
        <div
          ref={bodyRef}
          className="@container min-w-0 flex-1 overflow-y-auto px-4"
        >
          <div className="mx-auto max-w-[46rem]">
            <DocEditor
              key={`${docId}-${reloadCount}`}
              doc={doc.data}
              channelId={channelId}
              clientId={clientId}
              onReloadNeeded={onReloadNeeded}
              onDiscussionsChanged={discussionActions.refresh}
              onDiscussionStarted={onDiscussionStarted}
              onAgentThreadStarted={openAgentThread}
              onOpenThread={openAgentThread}
              onEditorReady={(instance) => {
                editorRef.current = instance;
              }}
              onStateChange={(state) => {
                setConnection(state.status);
                setVersion(state.version);
              }}
            />
          </div>
        </div>

        {panelOpen && agentTaskId ? (
          <aside className="@2xl:static absolute inset-y-0 right-0 @2xl:z-auto z-10 flex @2xl:w-96 w-full @2xl:shrink-0 flex-col border-(--gray-5) border-l bg-(--gray-1)">
            <DocAgentThread
              taskId={agentTaskId}
              channelId={channelId}
              onAddToPage={addAgentAnswerToPage}
              onClose={() => setAgentTaskId(null)}
            />
          </aside>
        ) : panelOpen ? (
          <DiscussionsPanel
            threads={threads}
            isLoading={discussions.isLoading}
            selectedAnchorKey={selectedAnchorKey}
            pendingAnchor={pendingAnchor}
            onSelect={setSelectedAnchorKey}
            onReply={(threadId, content) =>
              discussionActions.reply.mutateAsync({ threadId, content })
            }
            onStartThread={async (content) => {
              if (!pendingAnchor) return;
              await discussionActions.start.mutateAsync({
                content,
                anchorKey: pendingAnchor.anchorKey,
                anchorText: pendingAnchor.anchorText,
              });
              setPendingAnchor(null);
            }}
            onCancelPending={() => setPendingAnchor(null)}
            onResolveChange={(threadId, resolved) =>
              discussionActions.setResolved.mutate({ threadId, resolved })
            }
            onClose={() => setPanelOpen(false)}
          />
        ) : null}
      </div>

      {connection === "offline" ? (
        <Text
          size="sm"
          className="border-(--gray-5) border-t px-4 py-1 text-(--amber-11)"
        >
          Not connected. Your writing is kept here and sent when the connection
          comes back.
        </Text>
      ) : null}
    </div>
  );
}
