import type { DocSchemas } from "@posthog/api-client/docs";
import { searchInsightsForDoc } from "@posthog/api-client/docs";
import { Button, Separator, Text } from "@posthog/quill";
import { useOrgMembers } from "@posthog/ui/features/canvas/hooks/useOrgMembers";
import { useTasks } from "@posthog/ui/features/tasks/useTasks";
import { AgentMark } from "@posthog/ui/primitives/AgentMark";
import type { Editor } from "@tiptap/core";
import { getSchema } from "@tiptap/core";
import { TaskItem, TaskList } from "@tiptap/extension-list";
import Mention from "@tiptap/extension-mention";
import Placeholder from "@tiptap/extension-placeholder";
import { EditorContent, useEditor } from "@tiptap/react";
import { BubbleMenu } from "@tiptap/react/menus";
import StarterKit from "@tiptap/starter-kit";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { DocCollab } from "../collab/collabExtension";
import { type RemoteCaret, RemoteCarets } from "../collab/remoteCarets";
import { useDocCollab } from "../collab/useDocCollab";
import { createDocPeopleMention } from "../extensions/createDocPeopleMention";
import {
  createDocSlashMenu,
  type DocSlashChoice,
} from "../extensions/createDocSlashMenu";
import { DiscussionAnchor } from "../extensions/DiscussionAnchor";
import { MetricRow, type MetricRowItem } from "../extensions/MetricRow";
import { ObjectBlock } from "../extensions/ObjectBlock";
import { ObjectChip } from "../extensions/ObjectChip";
import { TaskChip } from "../extensions/TaskChip";
import { THREAD_ATTRIBUTE, ThreadGutter } from "../extensions/ThreadGutter";
import { useAskAgentFromDoc } from "../hooks/useAskAgentFromDoc";
import { useCreateTaskFromDoc } from "../hooks/useCreateTaskFromDoc";
import { useDocsClient } from "../hooks/useDocsClient";
import { pruneUnknown } from "../prosemirror/pruneUnknown";
import { selectionText } from "../prosemirror/selectionText";
import { DocThreadGutter } from "./DocThreadGutter";
import "@posthog/ui/features/canvas/components/mention-chip.css";
import "./docs.css";

const MAX_TASK_RESULTS = 8;

export interface DocEditorProps {
  doc: DocSchemas.Doc;
  channelId: string;
  /** Stable per open editor; two windows on the same doc must not share it. */
  clientId: string;
  onReloadNeeded: () => void;
  onDiscussionsChanged: () => void;
  /** Opens the panel on a thread, after the anchor is written into the text. */
  onDiscussionStarted: (anchor: {
    anchorKey: string;
    anchorText: string;
  }) => void;
  /** A new agent thread was started from the page. */
  onAgentThreadStarted: (taskId: string) => void;
  /** Hands the editor to the page so it can put an agent answer in the doc. */
  onEditorReady: (editor: Editor | null) => void;
  /** Opens an existing thread from its mark in the margin. */
  onOpenThread: (taskId: string) => void;
  onStateChange?: (state: {
    status: "connecting" | "live" | "offline";
    version: number;
    peers: RemoteCaret[];
  }) => void;
}

/**
 * The doc body.
 *
 * Everything a person types goes out as prosemirror-collab steps and comes back
 * on the doc's live stream, so two windows converge without either one owning
 * the document. Adding a chart, a number, or a task happens in the `/` popup,
 * and tagging the agent captures the paragraph once the caret leaves it. No part
 * of writing a page opens a window.
 */
export function DocEditor({
  doc,
  channelId,
  clientId,
  onReloadNeeded,
  onDiscussionsChanged,
  onDiscussionStarted,
  onAgentThreadStarted,
  onEditorReady,
  onOpenThread,
  onStateChange,
}: DocEditorProps) {
  const { members } = useOrgMembers();
  const membersRef = useRef(members);
  membersRef.current = members;

  const docsClient = useDocsClient();
  const docsClientRef = useRef(docsClient);
  docsClientRef.current = docsClient;

  const { data: tasks } = useTasks({ showAllUsers: true });
  const tasksRef = useRef(tasks);
  tasksRef.current = tasks;

  const [agentError, setAgentError] = useState<string | null>(null);

  const createTask = useCreateTaskFromDoc({
    channelId,
    docId: doc.id,
    docTitle: doc.title,
  });
  const askAgent = useAskAgentFromDoc({
    channelId,
    docTitle: doc.title,
  });

  const pickRef = useRef<(choice: DocSlashChoice) => void>(() => undefined);
  const makeTaskRef = useRef<() => Promise<void>>(async () => undefined);

  const extensions = useMemo(
    () => [
      StarterKit,
      Placeholder.configure({
        placeholder: "Write, / for a block, @ for a person",
      }),
      TaskList,
      TaskItem.configure({ nested: true }),
      Mention.configure({ HTMLAttributes: { class: "mention-chip" } }),
      DiscussionAnchor,
      TaskChip.configure({ channelId }),
      ObjectChip,
      ObjectBlock,
      MetricRow,
      ThreadGutter,
      RemoteCarets,
      DocCollab.configure({ version: doc.version, clientId }),
      createDocPeopleMention({
        sessionId: `doc-${doc.id}`,
        people: () => membersRef.current,
      }),
      createDocSlashMenu({
        sessionId: `doc-${doc.id}`,
        sources: {
          insights: async (query) => {
            const client = docsClientRef.current;
            if (!client) return [];
            const found = await searchInsightsForDoc(
              client.client,
              client.projectId,
              query,
            );
            return found.map((insight) => ({
              shortId: insight.short_id,
              label: insight.name || insight.derived_name || insight.short_id,
            }));
          },
          tasks: (query) => {
            const needle = query.trim().toLowerCase();
            return (tasksRef.current ?? [])
              .filter((task) => task.channel === channelId)
              .filter(
                (task) => !needle || task.title.toLowerCase().includes(needle),
              )
              .slice(0, MAX_TASK_RESULTS)
              .map((task) => ({ taskId: task.id, label: task.title }));
          },
        },
        onPick: (choice) => pickRef.current(choice),
      }),
    ],
    // The editor is rebuilt per doc (the view is keyed on the id), so the
    // starting version is read once on purpose.
    [channelId, clientId, doc.id, doc.version],
  );

  // A page can name a node this build no longer has. Prune those rather than
  // handing ProseMirror a document it refuses, which shows an empty page.
  const content = useMemo(() => {
    const stored = doc.content;
    if (!stored) return { type: "doc", content: [{ type: "paragraph" }] };
    return pruneUnknown(stored, getSchema(extensions));
  }, [doc.content, extensions]);

  const editor = useEditor({
    extensions,
    content,
    editorProps: {
      attributes: { class: "doc-body focus:outline-none" },
      handleKeyDown: (_view, event) => {
        // ⌘↵ takes the line you are on: it becomes a task in this space.
        const takesLine =
          (event.metaKey || event.ctrlKey) && event.key === "Enter";
        if (!takesLine) return false;
        void makeTaskRef.current();
        return true;
      },
    },
  });

  const editorReadyRef = useRef(onEditorReady);
  editorReadyRef.current = onEditorReady;
  useEffect(() => {
    editorReadyRef.current(editor);
    return () => editorReadyRef.current(null);
  }, [editor]);

  const collab = useDocCollab({
    editor,
    docId: doc.id,
    clientId,
    initialVersion: doc.version,
    onReloadNeeded,
    onDiscussionChanged: onDiscussionsChanged,
  });

  const stateChangeRef = useRef(onStateChange);
  stateChangeRef.current = onStateChange;
  useEffect(() => {
    stateChangeRef.current?.({
      status: collab.status,
      version: collab.version,
      peers: collab.peers,
    });
  }, [collab.status, collab.version, collab.peers]);

  /** Asks about the selected words, and marks their paragraph with the thread. */
  const askAgentAboutSelection = useCallback(() => {
    if (!editor) return;
    const question = selectionText(editor.state);
    if (!question) return;

    const block = editor.state.doc
      .resolve(editor.state.selection.from)
      .before();
    setAgentError(null);

    void askAgent
      .mutateAsync({ question })
      .then((task) => {
        editor.view.dispatch(
          editor.state.tr.setNodeAttribute(block, THREAD_ATTRIBUTE, task.id),
        );
        onAgentThreadStarted(task.id);
      })
      .catch((error: unknown) =>
        setAgentError(
          error instanceof Error && error.message
            ? error.message
            : "The agent did not start.",
        ),
      );
  }, [askAgent, editor, onAgentThreadStarted]);

  const startDiscussionFromSelection = useCallback(() => {
    if (!editor) return;
    const { from, to } = editor.state.selection;
    if (from === to) return;
    const anchorText = selectionText(editor.state).slice(0, 280);
    const anchorKey = crypto.randomUUID();
    editor
      .chain()
      .focus()
      .setMark("discussionAnchor", { anchorKey, resolved: false })
      .run();
    onDiscussionStarted({ anchorKey, anchorText });
  }, [editor, onDiscussionStarted]);

  const makeTaskFromSelection = useCallback(async () => {
    if (!editor) return;
    const lineText = selectionText(editor.state);
    if (!lineText) return;

    const task = await createTask.mutateAsync({ lineText });
    editor
      .chain()
      .focus()
      .insertContent([
        { type: "taskChip", attrs: { taskId: task.id, label: task.title } },
        { type: "text", text: " " },
      ])
      .run();
  }, [createTask, editor]);

  makeTaskRef.current = makeTaskFromSelection;

  /** Appends to the row just above the caret, so a second number joins the first. */
  const addNumber = useCallback(
    (item: MetricRowItem) => {
      if (!editor) return;
      const { $from } = editor.state.selection;
      const before = $from.nodeBefore ?? $from.node(-1);
      const previousPos = $from.before($from.depth) - (before?.nodeSize ?? 0);
      const previous = editor.state.doc.nodeAt(Math.max(0, previousPos));

      if (previous?.type.name === "metricRow") {
        const items = Array.isArray(previous.attrs.items)
          ? (previous.attrs.items as MetricRowItem[])
          : [];
        editor.view.dispatch(
          editor.state.tr.setNodeAttribute(Math.max(0, previousPos), "items", [
            ...items,
            item,
          ]),
        );
        return;
      }

      editor
        .chain()
        .focus()
        .insertContent({ type: "metricRow", attrs: { items: [item] } })
        .run();
    },
    [editor],
  );

  pickRef.current = (choice: DocSlashChoice) => {
    if (!editor) return;
    switch (choice.kind) {
      case "taskList":
        editor.chain().focus().toggleTaskList().run();
        return;
      case "discussion":
        startDiscussionFromSelection();
        return;
      case "sql":
        editor
          .chain()
          .focus()
          .insertContent({
            type: "objectBlock",
            attrs: { mode: "hogql", query: null },
          })
          .run();
        return;
      case "insight":
        editor
          .chain()
          .focus()
          .insertContent({
            type: "objectBlock",
            attrs: {
              mode: "insight",
              shortId: choice.shortId,
              title: choice.label,
            },
          })
          .run();
        return;
      case "metric":
        addNumber({ label: choice.label, shortId: choice.shortId });
        return;
      case "task":
        editor
          .chain()
          .focus()
          .insertContent([
            {
              type: "taskChip",
              attrs: { taskId: choice.taskId, label: choice.label },
            },
            { type: "text", text: " " },
          ])
          .run();
        return;
    }
  };

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      {editor ? (
        <BubbleMenu
          editor={editor}
          className="z-50 flex items-center gap-0.5 rounded-(--radius-3) border border-(--gray-6) bg-(--gray-1) p-1 shadow-lg"
          // Pressing a button here must not blur the editor: a blurred
          // contenteditable collapses its selection, and every action on this
          // toolbar acts on the selection.
          onMouseDown={(event) => event.preventDefault()}
        >
          <Button
            size="sm"
            variant="default"
            disabled={askAgent.isPending}
            onClick={askAgentAboutSelection}
          >
            <AgentMark size={12} />
            {askAgent.isPending ? "Asking…" : "Ask the agent"}
          </Button>
          <Button
            size="sm"
            variant="default"
            onClick={startDiscussionFromSelection}
          >
            Discuss
          </Button>
          <Button
            size="sm"
            variant="default"
            disabled={createTask.isPending}
            onClick={() => void makeTaskFromSelection()}
          >
            {createTask.isPending ? "Starting…" : "Make a task"}
          </Button>
          <Separator orientation="vertical" className="mx-0.5 h-4" />
          <Button
            size="sm"
            variant="default"
            aria-label="Bold"
            onClick={() => editor.chain().focus().toggleBold().run()}
          >
            <span className="font-semibold">B</span>
          </Button>
          <Button
            size="sm"
            variant="default"
            aria-label="Heading"
            onClick={() =>
              editor.chain().focus().toggleHeading({ level: 2 }).run()
            }
          >
            H2
          </Button>
        </BubbleMenu>
      ) : null}

      <div className="relative">
        <EditorContent editor={editor} className="min-h-0 flex-1" />
        <DocThreadGutter editor={editor} onOpen={onOpenThread} />
      </div>

      {agentError ? (
        <div className="flex items-center gap-2 py-2">
          <Text size="sm" className="text-(--tomato-11)">
            The agent did not start. Select the words and try again.
          </Text>
          <button
            type="button"
            className="cursor-pointer text-(--gray-10) text-xs underline decoration-(--gray-7) underline-offset-[3px] hover:text-(--gray-12)"
            onClick={() => setAgentError(null)}
          >
            Dismiss
          </button>
        </div>
      ) : null}
    </div>
  );
}
