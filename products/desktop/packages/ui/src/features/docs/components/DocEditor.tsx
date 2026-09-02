import {
  ChatsCircleIcon,
  CheckSquareIcon,
  CodeIcon,
  EyeIcon,
  LinkIcon,
  TextBIcon,
  TextHTwoIcon,
  TextItalicIcon,
  TextStrikethroughIcon,
} from "@phosphor-icons/react";
import type { DocSchemas } from "@posthog/api-client/docs";
import { searchInsightsForDoc } from "@posthog/api-client/docs";
import {
  Button,
  Input,
  Separator,
  Text,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { useOrgMembers } from "@posthog/ui/features/canvas/hooks/useOrgMembers";
import { useTasks } from "@posthog/ui/features/tasks/useTasks";
import type { Editor } from "@tiptap/core";
import { getSchema } from "@tiptap/core";
import { TaskItem, TaskList } from "@tiptap/extension-list";
import Placeholder from "@tiptap/extension-placeholder";
import { NodeSelection } from "@tiptap/pm/state";
import { EditorContent, useEditor } from "@tiptap/react";
import { BubbleMenu, type BubbleMenuProps } from "@tiptap/react/menus";
import StarterKit from "@tiptap/starter-kit";
import type React from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { DocCollab } from "../collab/collabExtension";
import { type RemoteCaret, RemoteCarets } from "../collab/remoteCarets";
import { useDocCollab } from "../collab/useDocCollab";
import { createDocDataRequest } from "../extensions/createDocDataRequest";
import { createDocPeopleMention } from "../extensions/createDocPeopleMention";
import {
  createDocSlashMenu,
  type DocSlashChoice,
} from "../extensions/createDocSlashMenu";
import { DataRequest, type DataRequestAttrs } from "../extensions/DataRequest";
import { DataValue, type DataValueAttrs } from "../extensions/DataValue";
import { DiscussionAnchor } from "../extensions/DiscussionAnchor";
import { MetricRow } from "../extensions/MetricRow";
import { ObjectBlock } from "../extensions/ObjectBlock";
import { ObjectChip } from "../extensions/ObjectChip";
import { PersonMention } from "../extensions/PersonMention";
import { TaskChip } from "../extensions/TaskChip";
import { useAskDataFromDoc } from "../hooks/useAskDataFromDoc";
import { useCreateTaskFromDoc } from "../hooks/useCreateTaskFromDoc";
import { useDocsClient } from "../hooks/useDocsClient";
import { refFromUrl } from "../prosemirror/posthogUrl";
import { pruneUnknown } from "../prosemirror/pruneUnknown";
import { selectionText } from "../prosemirror/selectionText";
import {
  type DataAnswer,
  DataRequestWatchers,
  type WatchedDataPoint,
} from "./DataRequestWatchers";
import { DocBlockGutter } from "./DocBlockGutter";
import { DocThreadGutter } from "./DocThreadGutter";
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
  /** A section was marked to be watched; the page starts the loop and its thread. */
  onWatchStarted: (anchor: { anchorKey: string; anchorText: string }) => void;
  /** A data point was asked for; the page opens its thread on the request. */
  onDataRequested: (request: {
    requestId: string;
    question: string;
    taskId: string;
  }) => void;
  /** A run was started, so the warm pool has to refill. */
  onAgentStarted: () => void;
  /** Hands the editor to the page so it can put an agent answer in the doc. */
  onEditorReady: (editor: Editor | null) => void;
  /** Opens a thread from its mark in the margin, by its anchor key. */
  onOpenThread: (anchorKey: string) => void;
  threads: DocSchemas.DiscussionThread[];
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
  onWatchStarted,
  onDataRequested,
  onAgentStarted,
  onEditorReady,
  onOpenThread,
  threads,
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
  const [watched, setWatched] = useState<WatchedDataPoint[]>([]);
  /** Set while the toolbar is asking for a link's address. */
  const [linkDraft, setLinkDraft] = useState<string | null>(null);
  const linkOpenRef = useRef(false);
  const openLink = useCallback((draft: string | null) => {
    linkOpenRef.current = draft !== null;
    setLinkDraft(draft);
  }, []);

  const createTask = useCreateTaskFromDoc({
    channelId,
    docId: doc.id,
    docTitle: doc.title,
  });
  const askData = useAskDataFromDoc({
    channelId,
    docTitle: doc.title,
  });

  const pickRef = useRef<(choice: DocSlashChoice) => void>(() => undefined);
  const pickDataRef = useRef<
    (
      choice:
        | { kind: "insight"; shortId: string; label: string }
        | { kind: "ask"; question: string },
    ) => void
  >(() => undefined);
  const makeTaskRef = useRef<() => Promise<void>>(async () => undefined);

  const extensions = useMemo(
    () => [
      StarterKit,
      Placeholder.configure({
        // The empty page says everything it can do; an empty line further down
        // says only what it is waiting for.
        placeholder: ({ editor, node }) =>
          node.type.name !== "paragraph"
            ? ""
            : editor.isEmpty
              ? "Write, + for data, / for a block, @ for a person"
              : "/ for a block",
        showOnlyCurrent: true,
      }),
      TaskList,
      TaskItem.configure({ nested: true }),
      PersonMention,
      DiscussionAnchor,
      TaskChip,
      ObjectChip,
      ObjectBlock,
      MetricRow,
      DataRequest,
      DataValue,
      RemoteCarets,
      DocCollab.configure({ version: doc.version, clientId }),
      createDocPeopleMention({
        sessionId: `doc-${doc.id}`,
        people: () => membersRef.current,
      }),
      createDocSlashMenu({
        sessionId: `doc-${doc.id}`,
        onPick: (choice) => pickRef.current(choice),
      }),
      createDocDataRequest({
        sessionId: `doc-${doc.id}`,
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
        onPick: (choice) => pickDataRef.current(choice),
      }),
    ],
    // The editor is rebuilt per doc (the view is keyed on the id), so the
    // starting version is read once on purpose.
    [clientId, doc.id, doc.version],
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
      // A PostHog link becomes the thing it points at, not a URL.
      handlePaste: (view, event) => {
        const ref = refFromUrl(
          event.clipboardData?.getData("text/plain") ?? "",
        );
        if (!ref) return false;
        const node = view.state.schema.nodeFromJSON(ref);
        view.dispatch(
          view.state.tr.replaceSelectionWith(node, false).insertText(" "),
        );
        return true;
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

  // The page itself is the list of what it is waiting for, so a reload keeps
  // watching the requests it left behind, and a value keeps listening for a
  // newer query on its thread.
  useEffect(() => {
    if (!editor) return;
    const scan = () => {
      const found: WatchedDataPoint[] = [];
      editor.state.doc.descendants((node) => {
        if (node.type.name === "dataRequest") {
          const { requestId, state } = node.attrs as DataRequestAttrs;
          if (requestId && (state === "asking" || state === "reply")) {
            found.push({ requestId, kind: "request", query: null });
          }
          return;
        }
        if (node.type.name === "dataValue") {
          const { requestId, query } = node.attrs as DataValueAttrs;
          if (requestId) found.push({ requestId, kind: "value", query });
        }
      });
      setWatched((current) =>
        current.length === found.length &&
        current.every(
          (point, index) =>
            point.requestId === found[index]?.requestId &&
            point.kind === found[index]?.kind &&
            point.query === found[index]?.query,
        )
          ? current
          : found,
      );
    };
    scan();
    editor.on("update", scan);
    return () => {
      editor.off("update", scan);
    };
  }, [editor]);

  /** Finds a request or a value by its id, wherever the page has moved it to. */
  const findDataRequest = useCallback(
    (
      requestId: string,
      type: "dataRequest" | "dataValue" = "dataRequest",
    ): number | null => {
      if (!editor) return null;
      let found: number | null = null;
      editor.state.doc.descendants((node, pos) => {
        if (node.type.name === type && node.attrs.requestId === requestId) {
          found = pos;
        }
      });
      return found;
    },
    [editor],
  );

  const updateDataRequest = useCallback(
    (requestId: string, attrs: Partial<DataRequestAttrs>) => {
      if (!editor) return;
      const pos = findDataRequest(requestId);
      if (pos === null) return;
      const tr = editor.state.tr;
      for (const [key, value] of Object.entries(attrs)) {
        tr.setNodeAttribute(pos, key, value);
      }
      editor.view.dispatch(tr);
    },
    [editor, findDataRequest],
  );

  /** Asks for data, and holds the place the answer will take. */
  const askDataFromDoc = useCallback(
    (question: string) => {
      if (!editor) return;
      const requestId = crypto.randomUUID();
      setAgentError(null);
      onAgentStarted();
      editor
        .chain()
        .focus()
        .insertContent({
          type: "dataRequest",
          attrs: {
            requestId,
            question,
            taskId: null,
            state: "asking",
            askedAt: Date.now(),
          },
        })
        .run();

      void askData
        .mutateAsync({ question, requestId })
        .then((task) => {
          updateDataRequest(requestId, { taskId: task.id });
          onDataRequested({ requestId, question, taskId: task.id });
        })
        .catch((error: unknown) => {
          updateDataRequest(requestId, { state: "failed" });
          setAgentError(
            error instanceof Error && error.message
              ? error.message
              : "The agent did not start.",
          );
        });
    },
    [askData, editor, onAgentStarted, onDataRequested, updateDataRequest],
  );

  /** A data point the project already measures goes in with no run at all. */
  const putDataValue = useCallback(
    (shortId: string, label: string) => {
      if (!editor) return;
      editor
        .chain()
        .focus()
        // No trailing space: the caret sits after the point, so a comma reads
        // as a comma. A word after it takes the space the writer types.
        .insertContent({ type: "dataValue", attrs: { shortId, label } })
        .run();
    },
    [editor],
  );

  pickDataRef.current = (choice) => {
    if (choice.kind === "insight") {
      putDataValue(choice.shortId, choice.label);
      return;
    }
    askDataFromDoc(choice.question);
  };

  /** Puts what the thread found where the request was, or updates the value. */
  const resolveDataRequest = useCallback(
    (requestId: string, answer: DataAnswer) => {
      if (!editor) return;
      if (answer.kind === "reply") {
        updateDataRequest(requestId, { state: "reply" });
        return;
      }
      if (answer.kind === "ended") {
        updateDataRequest(requestId, {
          state: answer.failed ? "failed" : "answered",
        });
        return;
      }

      const valuePos = findDataRequest(requestId, "dataValue");
      if (valuePos !== null) {
        const tr = editor.state.tr;
        tr.setNodeAttribute(valuePos, "query", answer.query);
        tr.setNodeAttribute(valuePos, "label", answer.label);
        tr.setNodeAttribute(valuePos, "note", answer.note);
        editor.view.dispatch(tr);
        return;
      }
      const pos = findDataRequest(requestId);
      const node = pos === null ? null : editor.state.doc.nodeAt(pos);
      if (pos === null || !node) return;
      const question = String(node.attrs.question ?? "");
      editor.view.dispatch(
        editor.state.tr.replaceWith(
          pos,
          pos + node.nodeSize,
          editor.schema.nodeFromJSON({
            type: "dataValue",
            attrs: {
              query: answer.query,
              label: answer.label || question,
              note: answer.note,
              requestId,
            },
          }),
        ),
      );
    },
    [editor, findDataRequest, updateDataRequest],
  );

  /**
   * The toolbar is for words. A selected block, a code block, or a cursor in a
   * block's own editor gets nothing; the link field keeps it while it is open.
   */
  const showToolbar = useCallback<NonNullable<BubbleMenuProps["shouldShow"]>>(
    ({ editor: current, view, state }) => {
      if (linkOpenRef.current) return true;
      if (!current.isEditable || !view.hasFocus()) return false;
      const { selection } = state;
      if (selection.empty || selection instanceof NodeSelection) return false;
      if (current.isActive("codeBlock")) return false;
      return (
        state.doc.textBetween(selection.from, selection.to, " ").trim().length >
        0
      );
    },
    [],
  );

  /** Marks the selection and hands its key on; a thread or a watch hangs off it. */
  const markSelection = useCallback(
    (
      kind: "text" | "watch",
    ): { anchorKey: string; anchorText: string } | null => {
      if (!editor) return null;
      const { from, to } = editor.state.selection;
      if (from === to) return null;
      const anchorText = selectionText(editor.state).slice(0, 280);
      const anchorKey = crypto.randomUUID();
      editor
        .chain()
        .focus()
        .setMark("discussionAnchor", { anchorKey, kind, resolved: false })
        .run();
      return { anchorKey, anchorText };
    },
    [editor],
  );

  const startDiscussionFromSelection = useCallback(() => {
    const anchor = markSelection("text");
    if (anchor) onDiscussionStarted(anchor);
  }, [markSelection, onDiscussionStarted]);

  const watchSelection = useCallback(() => {
    const anchor = markSelection("watch");
    if (anchor) onWatchStarted(anchor);
  }, [markSelection, onWatchStarted]);

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

  pickRef.current = (choice: DocSlashChoice) => {
    if (!editor) return;
    switch (choice.kind) {
      case "heading":
        editor.chain().focus().toggleHeading({ level: choice.level }).run();
        return;
      case "code":
        editor.chain().focus().toggleCodeBlock().run();
        return;
      case "bulletList":
        editor.chain().focus().toggleBulletList().run();
        return;
      case "orderedList":
        editor.chain().focus().toggleOrderedList().run();
        return;
      case "taskList":
        editor.chain().focus().toggleTaskList().run();
        return;
      case "quote":
        editor.chain().focus().toggleBlockquote().run();
        return;
      case "divider":
        editor.chain().focus().setHorizontalRule().run();
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
      case "data":
        // Teaches the trigger by typing it: the popup opens on the `+` and the
        // person keeps writing what they want to see.
        editor.chain().focus().insertContent("+").run();
        return;
    }
  };

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <DataRequestWatchers
        watched={watched}
        threads={threads}
        tasks={tasks ?? []}
        onAnswer={resolveDataRequest}
      />
      {editor ? (
        <BubbleMenu
          editor={editor}
          shouldShow={showToolbar}
          className="z-50 flex items-center gap-0.5 rounded-(--radius-3) border border-(--gray-6) bg-(--gray-1) p-1 shadow-lg"
          // Pressing a button here must not blur the editor: a blurred
          // contenteditable collapses its selection, and every action on this
          // toolbar acts on the selection.
          onMouseDown={(event) => event.preventDefault()}
        >
          {linkDraft !== null ? (
            <>
              <Input
                autoFocus
                value={linkDraft}
                placeholder="Paste a link"
                className="h-7 w-56 text-[13px]"
                onChange={(event: React.ChangeEvent<HTMLInputElement>) =>
                  openLink(event.target.value)
                }
                onKeyDown={(event: React.KeyboardEvent<HTMLInputElement>) => {
                  if (event.key === "Escape") {
                    openLink(null);
                    return;
                  }
                  if (event.key !== "Enter") return;
                  const href = linkDraft.trim();
                  openLink(null);
                  if (!href) {
                    editor.chain().focus().unsetLink().run();
                    return;
                  }
                  editor.chain().focus().setLink({ href }).run();
                }}
              />
              <Button
                size="sm"
                variant="default"
                onClick={() => openLink(null)}
              >
                Cancel
              </Button>
            </>
          ) : (
            <>
              <Button
                size="sm"
                variant="default"
                onClick={startDiscussionFromSelection}
              >
                <ChatsCircleIcon size={13} />
                Discuss
              </Button>
              <Button size="sm" variant="default" onClick={watchSelection}>
                <EyeIcon size={13} />
                Watch
              </Button>
              <Button
                size="sm"
                variant="default"
                disabled={createTask.isPending}
                onClick={() => void makeTaskFromSelection()}
              >
                <CheckSquareIcon size={13} />
                {createTask.isPending ? "Starting…" : "Make a task"}
              </Button>
              <Separator orientation="vertical" className="mx-0.5 h-4" />
              {/* What the words do is said in words; what they look like is a glyph,
              so the row does not read as five labels of equal weight. */}
              <Tooltip>
                <TooltipTrigger
                  render={
                    <Button
                      size="icon"
                      variant="default"
                      aria-label="Bold"
                      onClick={() => editor.chain().focus().toggleBold().run()}
                    />
                  }
                >
                  <TextBIcon size={13} />
                </TooltipTrigger>
                <TooltipContent>Bold</TooltipContent>
              </Tooltip>
              <Tooltip>
                <TooltipTrigger
                  render={
                    <Button
                      size="icon"
                      variant="default"
                      aria-label="Italic"
                      onClick={() =>
                        editor.chain().focus().toggleItalic().run()
                      }
                    />
                  }
                >
                  <TextItalicIcon size={13} />
                </TooltipTrigger>
                <TooltipContent>Italic</TooltipContent>
              </Tooltip>
              <Tooltip>
                <TooltipTrigger
                  render={
                    <Button
                      size="icon"
                      variant="default"
                      aria-label="Code"
                      onClick={() => editor.chain().focus().toggleCode().run()}
                    />
                  }
                >
                  <CodeIcon size={13} />
                </TooltipTrigger>
                <TooltipContent>Code</TooltipContent>
              </Tooltip>
              <Tooltip>
                <TooltipTrigger
                  render={
                    <Button
                      size="icon"
                      variant="default"
                      aria-label="Heading"
                      onClick={() =>
                        editor.chain().focus().toggleHeading({ level: 2 }).run()
                      }
                    />
                  }
                >
                  <TextHTwoIcon size={13} />
                </TooltipTrigger>
                <TooltipContent>Heading</TooltipContent>
              </Tooltip>
              <Tooltip>
                <TooltipTrigger
                  render={
                    <Button
                      size="icon"
                      variant="default"
                      aria-label="Strikethrough"
                      onClick={() =>
                        editor.chain().focus().toggleStrike().run()
                      }
                    />
                  }
                >
                  <TextStrikethroughIcon size={13} />
                </TooltipTrigger>
                <TooltipContent>Strikethrough</TooltipContent>
              </Tooltip>
              <Tooltip>
                <TooltipTrigger
                  render={
                    <Button
                      size="icon"
                      variant="default"
                      aria-label="Link"
                      onClick={() =>
                        openLink(editor.getAttributes("link").href ?? "")
                      }
                    />
                  }
                >
                  <LinkIcon size={13} />
                </TooltipTrigger>
                <TooltipContent>Link</TooltipContent>
              </Tooltip>
            </>
          )}
        </BubbleMenu>
      ) : null}

      <div className="relative">
        <EditorContent editor={editor} className="min-h-0 flex-1" />
        <DocBlockGutter editor={editor} />
        <DocThreadGutter
          editor={editor}
          threads={threads}
          tasks={tasks ?? []}
          onOpen={onOpenThread}
        />
      </div>

      {agentError ? (
        <div className="flex items-center gap-2 py-2">
          <Text size="sm" className="text-(--tomato-11)">
            The agent did not start. Ask for the data point again.
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
