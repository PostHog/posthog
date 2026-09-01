import type { DocSchemas } from "@posthog/api-client/docs";
import { Button, Separator } from "@posthog/quill";
import { useOrgMembers } from "@posthog/ui/features/canvas/hooks/useOrgMembers";
import type { Editor } from "@tiptap/core";
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
  type DocBlockKind,
} from "../extensions/createDocSlashMenu";
import { DiscussionAnchor } from "../extensions/DiscussionAnchor";
import { MetricRow } from "../extensions/MetricRow";
import { ObjectBlock } from "../extensions/ObjectBlock";
import { ObjectChip } from "../extensions/ObjectChip";
import { TaskChip } from "../extensions/TaskChip";
import { useAskAgentFromDoc } from "../hooks/useAskAgentFromDoc";
import { useCreateTaskFromDoc } from "../hooks/useCreateTaskFromDoc";
import { AskAgentDialog } from "./AskAgentDialog";
import { InsightPickerDialog, type PickedInsight } from "./InsightPickerDialog";
import { LinkTaskDialog, type PickedTask } from "./LinkTaskDialog";
import { SqlBlockDialog } from "./SqlBlockDialog";
import "./docs.css";

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
  onStateChange?: (state: {
    status: "connecting" | "live" | "offline";
    version: number;
    peers: RemoteCaret[];
  }) => void;
}

type PickerMode = null | "insight" | "metricRow" | "sql" | "task";

const PICKER_FOR_BLOCK: Record<DocBlockKind, PickerMode> = {
  sql: "sql",
  insight: "insight",
  metricRow: "metricRow",
  task: "task",
  taskList: null,
  discussion: null,
};

/**
 * The doc body.
 *
 * Everything a person types goes out as prosemirror-collab steps and comes back
 * on the doc's live stream, so two windows converge without either one owning
 * the document.
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
  onStateChange,
}: DocEditorProps) {
  const [picker, setPicker] = useState<PickerMode>(null);
  const [agentContext, setAgentContext] = useState<string | null>(null);
  const { members } = useOrgMembers();
  const membersRef = useRef(members);
  membersRef.current = members;

  const createTask = useCreateTaskFromDoc({
    channelId,
    docId: doc.id,
    docTitle: doc.title,
  });
  const askAgent = useAskAgentFromDoc({
    channelId,
    docId: doc.id,
    docTitle: doc.title,
  });

  // The slash menu is built once with the editor, but its actions need the
  // callbacks defined below, so it reads them through a ref.
  const pickRef = useRef<(kind: DocBlockKind) => void>(() => undefined);
  const makeTaskRef = useRef<() => Promise<void>>(async () => undefined);
  const askAgentRef = useRef<() => void>(() => undefined);

  const extensions = useMemo(
    () => [
      StarterKit,
      Placeholder.configure({ placeholder: "Write, or press / for a block" }),
      TaskList,
      TaskItem.configure({ nested: true }),
      Mention.configure({ HTMLAttributes: { class: "doc-mention" } }),
      DiscussionAnchor,
      TaskChip.configure({ channelId }),
      ObjectChip,
      ObjectBlock,
      MetricRow,
      RemoteCarets,
      DocCollab.configure({ version: doc.version, clientId }),
      createDocPeopleMention({
        sessionId: `doc-${doc.id}`,
        people: () => membersRef.current,
        onAskAgent: () => askAgentRef.current(),
      }),
      createDocSlashMenu({
        sessionId: `doc-${doc.id}`,
        onPick: (kind) => pickRef.current(kind),
      }),
    ],
    // The editor is rebuilt per doc (the view is keyed on the id), so the
    // starting version is read once on purpose.
    [channelId, clientId, doc.id, doc.version],
  );

  const editor = useEditor({
    extensions,
    content: doc.content ?? { type: "doc", content: [{ type: "paragraph" }] },
    editorProps: {
      attributes: {
        class: "doc-body focus:outline-none",
      },
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

  const collab = useDocCollab({
    editor,
    docId: doc.id,
    clientId,
    initialVersion: doc.version,
    onReloadNeeded,
    onDiscussionChanged: onDiscussionsChanged,
  });

  const editorReadyRef = useRef(onEditorReady);
  editorReadyRef.current = onEditorReady;
  useEffect(() => {
    editorReadyRef.current(editor);
    return () => editorReadyRef.current(null);
  }, [editor]);

  const stateChangeRef = useRef(onStateChange);
  stateChangeRef.current = onStateChange;
  useEffect(() => {
    stateChangeRef.current?.({
      status: collab.status,
      version: collab.version,
      peers: collab.peers,
    });
  }, [collab.status, collab.version, collab.peers]);

  const startDiscussionFromSelection = useCallback(() => {
    if (!editor) return;
    const { from, to } = editor.state.selection;
    if (from === to) return;
    const anchorText = editor.state.doc
      .textBetween(from, to, " ")
      .slice(0, 280);
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
    const { from, to } = editor.state.selection;
    const lineText =
      from === to
        ? editor.state.doc.resolve(from).parent.textContent.trim()
        : editor.state.doc.textBetween(from, to, " ");
    if (!lineText.trim()) return;

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

  const openAskAgent = useCallback(() => {
    if (!editor) return;
    const { from, to } = editor.state.selection;
    const context =
      from === to
        ? editor.state.doc.resolve(from).parent.textContent.trim()
        : editor.state.doc.textBetween(from, to, " ");
    setAgentContext(context.slice(0, 280));
  }, [editor]);

  askAgentRef.current = openAskAgent;

  pickRef.current = (kind: DocBlockKind) => {
    if (kind === "taskList") {
      editor?.chain().focus().toggleTaskList().run();
      return;
    }
    if (kind === "discussion") {
      startDiscussionFromSelection();
      return;
    }
    setPicker(PICKER_FOR_BLOCK[kind]);
  };

  const insertInsights = (insights: PickedInsight[], asRow: boolean) => {
    if (!editor || insights.length === 0) return;
    if (asRow) {
      editor
        .chain()
        .focus()
        .insertContent({
          type: "metricRow",
          attrs: {
            items: insights.map((insight) => ({
              label: insight.label,
              shortId: insight.shortId,
            })),
          },
        })
        .run();
      return;
    }
    const [insight] = insights;
    editor
      .chain()
      .focus()
      .insertContent({
        type: "objectBlock",
        attrs: {
          mode: "insight",
          shortId: insight.shortId,
          title: insight.label,
        },
      })
      .run();
  };

  const insertTaskChip = (task: PickedTask) => {
    editor
      ?.chain()
      .focus()
      .insertContent([
        { type: "taskChip", attrs: { taskId: task.taskId, label: task.label } },
        { type: "text", text: " " },
      ])
      .run();
  };

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      {editor ? (
        <BubbleMenu
          editor={editor}
          // z-50: the toolbar floats over the doc header, which would otherwise
          // take the clicks meant for it.
          className="z-50 flex items-center gap-1 rounded-(--radius-3) border border-(--gray-6) bg-(--gray-1) p-1 shadow-md"
          // Pressing a button here must not blur the editor: a blurred
          // contenteditable collapses its selection, and every action on this
          // toolbar acts on the selection.
          onMouseDown={(event) => event.preventDefault()}
        >
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
          <Button size="sm" variant="default" onClick={openAskAgent}>
            Ask the agent
          </Button>
          <Separator orientation="vertical" className="h-4" />
          <Button
            size="sm"
            variant="default"
            onClick={() => editor.chain().focus().toggleBold().run()}
          >
            B
          </Button>
          <Button
            size="sm"
            variant="default"
            onClick={() =>
              editor.chain().focus().toggleHeading({ level: 2 }).run()
            }
          >
            H2
          </Button>
        </BubbleMenu>
      ) : null}

      <EditorContent
        editor={editor}
        className="min-h-0 flex-1 overflow-y-auto"
      />

      <InsightPickerDialog
        open={picker === "insight" || picker === "metricRow"}
        multiple={picker === "metricRow"}
        onOpenChange={(open) => !open && setPicker(null)}
        onConfirm={(insights) =>
          insertInsights(insights, picker === "metricRow")
        }
      />
      <SqlBlockDialog
        open={picker === "sql"}
        onOpenChange={(open) => !open && setPicker(null)}
        onConfirm={(block) =>
          editor
            ?.chain()
            .focus()
            .insertContent({
              type: "objectBlock",
              attrs: {
                mode: "hogql",
                query: block.query,
                title: block.title || null,
              },
            })
            .run()
        }
      />
      <AskAgentDialog
        open={agentContext !== null}
        contextText={agentContext ?? ""}
        pending={askAgent.isPending}
        onOpenChange={(open) => !open && setAgentContext(null)}
        onConfirm={(question) => {
          void askAgent
            .mutateAsync({ question, contextText: agentContext ?? "" })
            .then((task) => {
              editor
                ?.chain()
                .focus()
                .insertContent([
                  {
                    type: "taskChip",
                    attrs: { taskId: task.id, label: task.title },
                  },
                  { type: "text", text: " " },
                ])
                .run();
              setAgentContext(null);
              onAgentThreadStarted(task.id);
            });
        }}
      />
      <LinkTaskDialog
        open={picker === "task"}
        channelId={channelId}
        onOpenChange={(open) => !open && setPicker(null)}
        onConfirm={insertTaskChip}
      />
    </div>
  );
}
