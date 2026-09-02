import type { DocSchemas } from "@posthog/api-client/docs";
import { runLoop } from "@posthog/api-client/loops";
import { cn } from "@posthog/quill";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import { useTaskChannels } from "@posthog/ui/features/canvas/hooks/useTaskChannels";
import { useCreateLoop } from "@posthog/ui/features/loops/hooks/useLoopMutations";
import { useLoopsClient } from "@posthog/ui/features/loops/hooks/useLoopsClient";
import { useTasks } from "@posthog/ui/features/tasks/useTasks";
import { toast } from "@posthog/ui/primitives/toast";
import type { Editor } from "@tiptap/core";
import {
  forwardRef,
  type ReactNode,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import type { RemoteCaret } from "../collab/remoteCarets";
import type { DocConnectionStatus } from "../collab/useDocCollab";
import {
  DOC_AGENT_ADAPTER,
  DOC_AGENT_MODEL,
  DOC_AGENT_REASONING_EFFORT,
  docTaskTitle,
} from "../hooks/docAgent";
import { watchLoopInstructions } from "../hooks/docThreadPrompt";
import {
  useDiscussionMutations,
  useDocDiscussions,
} from "../hooks/useDocDiscussions";
import { agentAnswerToContent } from "../prosemirror/agentAnswer";
import { DocAgentWarmKeeper } from "./DocAgentWarmKeeper";
import { DocEditor } from "./DocEditor";
import {
  DocThreadsPanel,
  type PendingThread,
  type ThreadsPanelView,
} from "./DocThreadsPanel";

/** Long enough to be seen, short enough to be gone before the next click. */
const ANCHOR_FLASH_MS = 1_600;
/** Weekday mornings: a report waits with the coffee, never in the night. */
const WATCH_CRON = "0 9 * * 1-5";

export interface DocCollabState {
  status: DocConnectionStatus;
  version: number;
  peers: RemoteCaret[];
}

export interface DocSurfaceHandle {
  /** Opens the threads list, or closes the panel when it is open. */
  toggleThreads: () => void;
  /** Scrolls another person's caret into view. */
  jumpToPeer: (clientId: string) => void;
}

/**
 * A doc's body and the threads beside it: the editor, the marks in its margin,
 * the panel a thread opens in, and every way the agent joins.
 *
 * It is the whole of what a page is, without the page's own chrome, so a page in
 * the tab row and the space's context notes are the same thing edited the same
 * way. The parent supplies the doc and hears about the connection and the threads.
 */
export const DocSurface = forwardRef<
  DocSurfaceHandle,
  {
    doc: DocSchemas.Doc;
    channelId: string;
    /** Bumped when the doc must start over from the stored version. */
    reloadCount: number;
    onReloadNeeded: () => void;
    onCollabState?: (state: DocCollabState) => void;
    onOpenThreadCount?: (count: number) => void;
    /** A thread to open beside the doc as it loads, by its anchor key. */
    openThreadKey?: string;
    /** Rendered above the body, inside its column: a title, a lede. */
    lead?: ReactNode;
    /** The body's column, when the surface is not a whole page. */
    columnClassName?: string;
    className?: string;
  }
>(function DocSurface(
  {
    doc,
    channelId,
    reloadCount,
    onReloadNeeded,
    onCollabState,
    onOpenThreadCount,
    openThreadKey,
    lead,
    columnClassName,
    className,
  },
  ref,
) {
  const docId = doc.id;
  const { channels } = useTaskChannels();
  const spaceName = channels.find((channel) => channel.id === channelId)?.name;
  const discussions = useDocDiscussions(docId);
  const discussionActions = useDiscussionMutations(docId);
  const { data: tasks } = useTasks({ showAllUsers: true });
  const { data: currentUser } = useCurrentUser();
  const createLoop = useCreateLoop();
  const loopsClient = useLoopsClient();

  /** Closed, the list, or one thread. */
  const [panel, setPanel] = useState<ThreadsPanelView | null>(() =>
    openThreadKey ? { view: "thread", anchorKey: openThreadKey } : null,
  );
  const [pendingAnchor, setPendingAnchor] = useState<PendingThread | null>(
    null,
  );
  // Bumped on every run started from this page; remounting refills the pool.
  const [warmNonce, setWarmNonce] = useState(0);
  const editorRef = useRef<Editor | null>(null);
  const bodyRef = useRef<HTMLDivElement>(null);

  // One id per open editor. Two windows on the same doc must never share it,
  // or each would treat the other's steps as its own.
  const editorKey = `${docId}:${reloadCount}`;
  const clientIdRef = useRef({ key: editorKey, id: crypto.randomUUID() });
  if (clientIdRef.current.key !== editorKey) {
    clientIdRef.current = { key: editorKey, id: crypto.randomUUID() };
  }
  const clientId = clientIdRef.current.id;

  const threads = discussions.data ?? [];
  const openCount = threads.filter((thread) => !thread.resolved).length;

  // A link can arrive while the page is already open, and it may name the
  // thread by its id rather than its anchor, the way the Activity feed does.
  useEffect(() => {
    if (openThreadKey) setPanel({ view: "thread", anchorKey: openThreadKey });
  }, [openThreadKey]);
  useEffect(() => {
    if (!panel || panel.view !== "thread") return;
    const byId = threads.find((thread) => thread.id === panel.anchorKey);
    if (byId) setPanel({ view: "thread", anchorKey: byId.anchor_key });
  }, [panel, threads]);
  useEffect(() => {
    onOpenThreadCount?.(openCount);
  }, [openCount, onOpenThreadCount]);

  const onDiscussionStarted = useCallback((anchor: PendingThread) => {
    setPendingAnchor(anchor);
    setPanel({ view: "thread", anchorKey: anchor.anchorKey });
  }, []);

  /** Takes a mark off the text once nothing hangs off it: a thread never sent, a watch that did not start. */
  const removeAnchor = useCallback((anchorKey: string) => {
    const editor = editorRef.current;
    if (!editor) return;
    const type = editor.schema.marks.discussionAnchor;
    const tr = editor.state.tr;
    editor.state.doc.descendants((node, pos) => {
      for (const mark of node.marks) {
        if (mark.type === type && mark.attrs.anchorKey === anchorKey) {
          tr.removeMark(pos, pos + node.nodeSize, mark);
        }
      }
    });
    if (tr.docChanged) editor.view.dispatch(tr);
  }, []);

  const cancelPending = useCallback(() => {
    setPendingAnchor((pending) => {
      if (pending) removeAnchor(pending.anchorKey);
      return null;
    });
  }, [removeAnchor]);

  const openThread = useCallback((anchorKey: string) => {
    setPanel({ view: "thread", anchorKey });
  }, []);

  const onAgentStarted = useCallback(() => {
    setWarmNonce((nonce) => nonce + 1);
  }, []);

  // A data request is a thread from the start, so its answer and any follow-up
  // live where every other conversation on the page lives.
  const onDataRequested = useCallback(
    (request: { requestId: string; question: string; taskId: string }) => {
      void discussionActions.start.mutateAsync({
        content: request.question,
        anchor_key: request.requestId,
        anchor_text: request.question.slice(0, 280),
        kind: "data",
        task_id: request.taskId,
        send_to_agent: true,
      });
    },
    [discussionActions.start],
  );

  // A watch is a loop on the space plus a thread on the section. The loop runs
  // once now, so the first report arrives while the section is still fresh.
  const onWatchStarted = useCallback(
    async (anchor: PendingThread) => {
      const title = docTaskTitle(anchor.anchorText, "Watched section");
      const docTitle = doc.title || "Untitled";
      setPanel({ view: "thread", anchorKey: anchor.anchorKey });
      try {
        const loop = await createLoop.mutateAsync({
          name: `Watch: ${title}`,
          description: `Keeps checking a section of the page "${docTitle}".`,
          instructions: watchLoopInstructions({
            anchorText: anchor.anchorText,
            docTitle,
          }),
          // A loop on a space's context posts to a shared feed, so it is the team's.
          visibility: "team",
          runtime_adapter: DOC_AGENT_ADAPTER,
          model: DOC_AGENT_MODEL,
          reasoning_effort: DOC_AGENT_REASONING_EFFORT,
          triggers: [
            {
              type: "schedule",
              config: {
                cron_expression: WATCH_CRON,
                timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
              },
            },
          ],
          context_target: spaceName
            ? { channel_id: channelId, name: spaceName }
            : null,
        });
        await discussionActions.start.mutateAsync({
          content: `Watching this. The agent checks it every weekday morning and reports here.`,
          anchor_key: anchor.anchorKey,
          anchor_text: anchor.anchorText.slice(0, 280),
          kind: "watch",
          loop_id: loop.id,
        });
        if (loopsClient) {
          await runLoop(loopsClient.client, loopsClient.projectId, loop.id);
        }
        onAgentStarted();
      } catch (error) {
        removeAnchor(anchor.anchorKey);
        setPanel((open) => (open?.view === "thread" ? { view: "list" } : open));
        const message = error instanceof Error ? error.message : String(error);
        toast.error("The watch did not start", {
          description: message.includes("Loops")
            ? "Loops are not on for this project yet."
            : message,
        });
      }
    },
    [
      channelId,
      createLoop,
      discussionActions.start,
      doc.title,
      loopsClient,
      onAgentStarted,
      removeAnchor,
      spaceName,
    ],
  );

  /** Shows the place a thread is about, and lights it for a moment. */
  const jumpToAnchor = useCallback((anchorKey: string) => {
    const body = bodyRef.current;
    if (!body) return;
    const target =
      body.querySelector(`[data-anchor-key="${anchorKey}"]`) ??
      body.querySelector(`[data-request-id="${anchorKey}"]`);
    if (!(target instanceof HTMLElement)) return;
    target.scrollIntoView({ block: "center", behavior: "smooth" });
    target.dataset.active = "true";
    setTimeout(() => {
      delete target.dataset.active;
    }, ANCHOR_FLASH_MS);
  }, []);

  useImperativeHandle(
    ref,
    () => ({
      toggleThreads: () => setPanel((open) => (open ? null : { view: "list" })),
      jumpToPeer: (peerClientId: string) => {
        const label = bodyRef.current?.querySelector(
          `[data-caret-client="${peerClientId}"]`,
        );
        label?.scrollIntoView({ block: "center", behavior: "smooth" });
      },
    }),
    [],
  );

  // The only path from an agent answer into the page. The text lands where the
  // caret is and stays selected, so it is obvious what arrived.
  const addAgentAnswerToPage = useCallback((text: string) => {
    const content = agentAnswerToContent(text);
    if (!content.length) return;
    editorRef.current?.chain().focus().insertContent(content).run();
  }, []);

  // A click on a marked phrase or a data point opens the right thread beside
  // the page. The listener is attached through a callback ref rather than an
  // effect: the body only mounts after the doc loads, so an effect with no
  // dependencies would run while there was nothing to attach to.
  const detachBody = useRef<(() => void) | null>(null);
  const attachBody = useCallback((node: HTMLDivElement | null) => {
    detachBody.current?.();
    detachBody.current = null;
    bodyRef.current = node;
    if (!node) return;

    const onClick = (event: MouseEvent) => {
      const target = event.target as HTMLElement | null;
      const key =
        target?.closest("[data-anchor-key]")?.getAttribute("data-anchor-key") ??
        target?.closest("[data-request-id]")?.getAttribute("data-request-id");
      if (!key) return;
      setPanel({ view: "thread", anchorKey: key });
    };

    node.addEventListener("click", onClick);
    detachBody.current = () => node.removeEventListener("click", onClick);
  }, []);

  return (
    // A side panel needs room. Below the container breakpoint it covers the doc
    // instead of squeezing it, which keeps the text readable in a narrow window.
    <div className={cn("@container relative flex min-h-0 flex-1", className)}>
      <DocAgentWarmKeeper key={warmNonce} />
      <div
        ref={attachBody}
        className={cn(
          "@container min-w-0 flex-1 overflow-y-auto",
          columnClassName ?? "@2xl:px-12 px-5 pt-7",
        )}
      >
        <div className="mx-auto w-full max-w-[52.25rem]">
          {lead}
          <DocEditor
            key={`${docId}-${reloadCount}`}
            doc={doc}
            channelId={channelId}
            clientId={clientId}
            onReloadNeeded={onReloadNeeded}
            onDiscussionsChanged={discussionActions.refresh}
            onDiscussionStarted={onDiscussionStarted}
            onWatchStarted={(anchor) => void onWatchStarted(anchor)}
            onDataRequested={onDataRequested}
            onAgentStarted={onAgentStarted}
            onOpenThread={openThread}
            threads={threads}
            onEditorReady={(instance) => {
              editorRef.current = instance;
            }}
            onStateChange={onCollabState}
          />
        </div>
      </div>

      {panel ? (
        <DocThreadsPanel
          view={panel}
          onView={setPanel}
          onClose={() => {
            setPanel(null);
            cancelPending();
          }}
          threads={threads}
          isLoading={discussions.isLoading}
          pending={pendingAnchor}
          onCancelPending={cancelPending}
          docId={docId}
          channelId={channelId}
          docTitle={doc.title || "Untitled"}
          tasks={tasks ?? []}
          currentUserEmail={currentUser?.email}
          onJumpToAnchor={jumpToAnchor}
          onAddToPage={addAgentAnswerToPage}
          onAgentStarted={onAgentStarted}
        />
      ) : null}
    </div>
  );
});
