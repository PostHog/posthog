import {
  openDocStream,
  saveDocSteps,
  sendDocCaret,
} from "@posthog/api-client/docs";
import { SseEventParser } from "@posthog/core/cloud-task/sse-parser";
import {
  getVersion,
  receiveTransaction,
  sendableSteps,
} from "@tiptap/pm/collab";
import { Step } from "@tiptap/pm/transform";
import type { Editor } from "@tiptap/react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useDocsClient } from "../hooks/useDocsClient";
import {
  REMOTE_CARET_TIMEOUT_MS,
  type RemoteCaret,
  remoteCaretsKey,
} from "./remoteCarets";

export type DocConnectionStatus = "connecting" | "live" | "offline";
export type DocSaveState = "saved" | "saving" | "reload-needed";

/** Long enough to batch a burst of typing, short enough that a peer sees it as live. */
const SAVE_DEBOUNCE_MS = 400;
/** Carets are cheap but not free; one ping per this window is enough to look continuous. */
const CARET_THROTTLE_MS = 250;
const CARET_PRUNE_INTERVAL_MS = 5_000;
const RECONNECT_BASE_MS = 500;
const RECONNECT_MAX_MS = 15_000;

export interface UseDocCollabOptions {
  editor: Editor | null;
  docId: string | null;
  clientId: string;
  /** Version the editor's starting content came from. */
  initialVersion: number;
  /** Called when the doc has moved on so far that the client must load it again. */
  onReloadNeeded: () => void;
  /** Called when a discussion on this doc changed, so the panel can refetch. */
  onDiscussionChanged?: () => void;
}

export interface DocCollabState {
  status: DocConnectionStatus;
  saveState: DocSaveState;
  version: number;
}

/**
 * Keeps one open doc in sync with the server.
 *
 * Outgoing: local steps are batched and posted; a rejected batch is rebased on
 * the steps that beat it and sent again. Incoming: the doc's server-sent stream
 * delivers other people's steps and carets, resuming from the last version it
 * saw whenever the connection drops.
 */
export function useDocCollab(options: UseDocCollabOptions): DocCollabState {
  const { editor, docId, clientId, initialVersion, onReloadNeeded } = options;
  const docsClient = useDocsClient();

  const [status, setStatus] = useState<DocConnectionStatus>("connecting");
  const [saveState, setSaveState] = useState<DocSaveState>("saved");
  const [version, setVersion] = useState(initialVersion);

  const editorRef = useRef<Editor | null>(editor);
  editorRef.current = editor;
  const reloadRef = useRef(onReloadNeeded);
  reloadRef.current = onReloadNeeded;
  const discussionRef = useRef(options.onDiscussionChanged);
  discussionRef.current = options.onDiscussionChanged;

  const caretsRef = useRef(new Map<string, RemoteCaret>());
  const versionRef = useRef(initialVersion);
  const sendingRef = useRef(false);

  const applyCarets = useCallback(() => {
    const activeEditor = editorRef.current;
    if (!activeEditor) return;
    const carets = [...caretsRef.current.values()];
    activeEditor.view.dispatch(
      activeEditor.state.tr.setMeta(remoteCaretsKey, carets),
    );
  }, []);

  const flush = useCallback(async (): Promise<void> => {
    const activeEditor = editorRef.current;
    if (!activeEditor || !docsClient || !docId || sendingRef.current) return;

    const sendable = sendableSteps(activeEditor.state);
    if (!sendable) return;

    sendingRef.current = true;
    setSaveState("saving");
    try {
      const result = await saveDocSteps(
        docsClient.client,
        docsClient.projectId,
        docId,
        {
          client_id: clientId,
          steps: sendable.steps.map((step) => step.toJSON()),
          version: sendable.version,
          content: activeEditor.getJSON() as Record<string, unknown>,
          text_content: activeEditor.getText(),
          cursor_head: activeEditor.state.selection.head,
        },
      );

      if (result.status === "accepted") {
        versionRef.current = result.doc.version;
        setVersion(result.doc.version);
        setSaveState("saved");
        return;
      }

      if (result.status === "stale") {
        setSaveState("reload-needed");
        reloadRef.current();
        return;
      }

      applyRemoteSteps(
        activeEditor,
        result.conflict.steps ?? [],
        result.conflict.client_ids ?? [],
      );
      versionRef.current = result.conflict.version;
      setVersion(result.conflict.version);
    } finally {
      sendingRef.current = false;
    }
  }, [clientId, docId, docsClient]);

  // Outgoing steps. Debounced so a burst of typing becomes one request, then
  // re-run until the editor has nothing left to send.
  useEffect(() => {
    if (!editor || !docId) return;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const schedule = () => {
      if (timer) clearTimeout(timer);
      timer = setTimeout(() => {
        void flush().then(() => {
          if (editorRef.current && sendableSteps(editorRef.current.state)) {
            schedule();
          }
        });
      }, SAVE_DEBOUNCE_MS);
    };

    editor.on("update", schedule);
    return () => {
      editor.off("update", schedule);
      if (timer) clearTimeout(timer);
    };
  }, [editor, docId, flush]);

  // Outgoing carets.
  useEffect(() => {
    if (!editor || !docId || !docsClient) return;
    let lastSentAt = 0;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const send = () => {
      lastSentAt = Date.now();
      const { anchor, head } = editor.state.selection;
      void sendDocCaret(docsClient.client, docsClient.projectId, docId, {
        client_id: clientId,
        version: versionRef.current,
        cursor: { anchor, head },
      }).catch(() => undefined);
    };

    const onSelection = () => {
      const sinceLast = Date.now() - lastSentAt;
      if (sinceLast >= CARET_THROTTLE_MS) {
        send();
        return;
      }
      if (timer) return;
      timer = setTimeout(() => {
        timer = null;
        send();
      }, CARET_THROTTLE_MS - sinceLast);
    };

    editor.on("selectionUpdate", onSelection);
    return () => {
      editor.off("selectionUpdate", onSelection);
      if (timer) clearTimeout(timer);
    };
  }, [editor, docId, docsClient, clientId]);

  // Incoming stream.
  useEffect(() => {
    if (!docId || !docsClient) return;
    const controller = new AbortController();
    let attempt = 0;
    let stopped = false;

    const readOnce = async (): Promise<void> => {
      setStatus("connecting");
      const response = await openDocStream(
        docsClient.client,
        docsClient.projectId,
        docId,
        {
          lastEventId: `${versionRef.current}-0`,
          signal: controller.signal,
        },
      );
      if (!response.body) throw new Error("Doc stream has no body");
      setStatus("live");

      const parser = new SseEventParser();
      const decoder = new TextDecoder();
      const reader = response.body.getReader();

      while (!stopped) {
        const { done, value } = await reader.read();
        if (done) return;
        for (const event of parser.parse(
          decoder.decode(value, { stream: true }),
        )) {
          handleStreamEvent(event);
        }
      }
    };

    const handleStreamEvent = (event: {
      event?: string;
      id?: string;
      data: unknown;
    }) => {
      if (event.event === "step") {
        const payload = event.data as { step?: unknown; client_id?: string };
        const streamVersion = Number.parseInt(
          event.id?.split("-")[0] ?? "",
          10,
        );
        if (Number.isFinite(streamVersion)) {
          versionRef.current = streamVersion;
          setVersion(streamVersion);
        }
        if (payload.client_id === clientId || !payload.step) return;
        const activeEditor = editorRef.current;
        if (activeEditor) {
          applyRemoteSteps(
            activeEditor,
            [payload.step],
            [payload.client_id ?? "unknown"],
          );
        }
        return;
      }

      if (event.event === "presence") {
        const payload = event.data as {
          client_id: string;
          user_name: string;
          cursor?: { anchor: number; head: number };
        };
        if (payload.client_id === clientId || !payload.cursor) return;
        caretsRef.current.set(payload.client_id, {
          clientId: payload.client_id,
          userName: payload.user_name,
          anchor: payload.cursor.anchor,
          head: payload.cursor.head,
          seenAt: Date.now(),
        });
        applyCarets();
        return;
      }

      if (event.event === "discussion") {
        discussionRef.current?.();
      }
    };

    const run = async () => {
      while (!stopped) {
        try {
          await readOnce();
          attempt = 0;
        } catch {
          if (stopped || controller.signal.aborted) return;
          setStatus("offline");
          await sleep(
            Math.min(RECONNECT_BASE_MS * 2 ** attempt++, RECONNECT_MAX_MS),
          );
        }
      }
    };

    void run();
    return () => {
      stopped = true;
      controller.abort();
      caretsRef.current.clear();
    };
  }, [docId, docsClient, clientId, applyCarets]);

  // Carets are lossy: drop the ones nobody has refreshed instead of waiting for
  // a goodbye that may never arrive.
  useEffect(() => {
    const interval = setInterval(() => {
      const cutoff = Date.now() - REMOTE_CARET_TIMEOUT_MS;
      let changed = false;
      for (const [id, caret] of caretsRef.current) {
        if (caret.seenAt < cutoff) {
          caretsRef.current.delete(id);
          changed = true;
        }
      }
      if (changed) applyCarets();
    }, CARET_PRUNE_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [applyCarets]);

  useEffect(() => {
    versionRef.current = initialVersion;
    setVersion(initialVersion);
  }, [initialVersion]);

  return { status, saveState, version };
}

function applyRemoteSteps(
  editor: Editor,
  rawSteps: unknown[],
  clientIds: string[],
): void {
  if (rawSteps.length === 0) return;
  const steps = rawSteps.map((raw) =>
    Step.fromJSON(editor.schema, raw as Record<string, unknown>),
  );
  editor.view.dispatch(
    receiveTransaction(editor.state, steps, clientIds, {
      mapSelectionBackward: true,
    }),
  );
}

/** The editor's own view of where it is, for callers that need it outside React state. */
export function currentEditorVersion(editor: Editor): number {
  return getVersion(editor.state);
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
