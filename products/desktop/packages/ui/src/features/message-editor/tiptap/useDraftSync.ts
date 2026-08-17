import {
  type EditorContent,
  type FileAttachment,
  isContentEmpty,
} from "@posthog/core/message-editor/content";
import { useDraftStore } from "@posthog/ui/features/message-editor/draftStore";
import type { Editor, JSONContent } from "@tiptap/core";
import { useCallback, useLayoutEffect, useRef, useState } from "react";

function tiptapJsonToEditorContent(json: JSONContent): EditorContent {
  const segments: EditorContent["segments"] = [];

  const traverse = (node: JSONContent) => {
    if (node.type === "text" && node.text) {
      segments.push({ type: "text", text: node.text });
    } else if (node.type === "hardBreak") {
      // Shift+Enter creates a hard break within a paragraph
      // Use two trailing spaces + newline for markdown line break (<br>)
      segments.push({ type: "text", text: "  \n" });
    } else if (node.type === "mentionChip" && node.attrs) {
      segments.push({
        type: "chip",
        chip: {
          type: node.attrs.type,
          id: node.attrs.id,
          label: node.attrs.label,
          pastedText: node.attrs.pastedText,
          skillPath: node.attrs.skillPath,
          skillSource: node.attrs.skillSource,
          skillName: node.attrs.skillName,
        },
      });
    } else if (node.type === "doc" && node.content) {
      // Add double newlines between paragraphs for markdown rendering
      // (single newlines in markdown become spaces, double newlines create paragraph breaks)
      for (let i = 0; i < node.content.length; i++) {
        if (i > 0) {
          segments.push({ type: "text", text: "\n\n" });
        }
        traverse(node.content[i]);
      }
    } else if (node.content) {
      for (const child of node.content) {
        traverse(child);
      }
    }
  };

  traverse(json);
  return { segments };
}

export function editorContentToTiptapJson(content: EditorContent): JSONContent {
  const paragraphs: JSONContent[] = [];
  let currentParagraphContent: JSONContent[] = [];

  const flushParagraph = () => {
    paragraphs.push({ type: "paragraph", content: currentParagraphContent });
    currentParagraphContent = [];
  };

  for (const seg of content.segments) {
    if (seg.type === "text") {
      const paragraphParts = seg.text.split("\n\n");
      for (let i = 0; i < paragraphParts.length; i++) {
        if (i > 0) {
          flushParagraph();
        }
        const lineParts = paragraphParts[i].split(/ {2}\n|\n/);
        for (let j = 0; j < lineParts.length; j++) {
          if (j > 0) {
            currentParagraphContent.push({ type: "hardBreak" });
          }
          if (lineParts[j]) {
            currentParagraphContent.push({ type: "text", text: lineParts[j] });
          }
        }
      }
    } else {
      currentParagraphContent.push({
        type: "mentionChip",
        attrs: {
          type: seg.chip.type,
          id: seg.chip.id,
          label: seg.chip.label,
          pastedText: seg.chip.pastedText ?? false,
          skillPath: seg.chip.skillPath,
          skillSource: seg.chip.skillSource,
          skillName: seg.chip.skillName,
        },
      });
    }
  }

  flushParagraph();

  if (paragraphs.length === 0) {
    paragraphs.push({ type: "paragraph", content: [] });
  }

  return {
    type: "doc",
    content: paragraphs,
  };
}

export interface DraftContext {
  taskId?: string;
  repoPath?: string | null;
}

export function useDraftSync(
  editor: Editor | null,
  sessionId: string,
  context?: DraftContext,
) {
  const hasRestoredRef = useRef(false);
  const lastSessionIdRef = useRef(sessionId);
  const lastEditorRef = useRef(editor);
  const editorRef = useRef(editor);
  editorRef.current = editor;

  const draftActions = useDraftStore((s) => s.actions);
  const draft = useDraftStore((s) => s.drafts[sessionId] ?? null);
  const pendingContent = useDraftStore(
    (s) => s.pendingContent[sessionId] ?? null,
  );
  const pendingInsert = useDraftStore(
    (s) => s.pendingInsert[sessionId] ?? null,
  );
  const hasHydrated = useDraftStore((s) => s._hasHydrated);

  // Reset restoration flag when sessionId changes (e.g., navigating between tasks)
  if (lastSessionIdRef.current !== sessionId) {
    lastSessionIdRef.current = sessionId;
    hasRestoredRef.current = false;
  }

  // Reset restoration flag when editor instance changes (e.g., when disabled state changes)
  if (lastEditorRef.current !== editor && editor !== null) {
    lastEditorRef.current = editor;
    hasRestoredRef.current = false;
  }

  // Set context for this session
  useLayoutEffect(() => {
    draftActions.setContext(sessionId, {
      taskId: context?.taskId,
      repoPath: context?.repoPath,
    });
    return () => {
      draftActions.removeContext(sessionId);
    };
  }, [sessionId, context?.taskId, context?.repoPath, draftActions]);

  // Restore draft on mount or when sessionId/editor changes
  useLayoutEffect(() => {
    if (!hasHydrated || !editor || hasRestoredRef.current) return;
    if (!draft || isContentEmpty(draft)) return;

    hasRestoredRef.current = true;

    if (typeof draft === "string") {
      editor.commands.setContent(draft);
    } else {
      editor.commands.setContent(editorContentToTiptapJson(draft));
    }
  }, [hasHydrated, draft, editor]);

  // Handle pending content (e.g., restoring queued messages after cancel)
  useLayoutEffect(() => {
    if (!editor || !pendingContent) return;

    editor.commands.setContent(editorContentToTiptapJson(pendingContent));
    editor.commands.focus("end", { scrollIntoView: false });
    draftActions.clearPendingContent(sessionId);
  }, [editor, pendingContent, sessionId, draftActions]);

  useLayoutEffect(() => {
    if (!editor || !pendingInsert) return;

    editor.commands.focus("end");
    editor.commands.insertContent(
      editorContentToTiptapJson(pendingInsert).content ?? [],
    );
    draftActions.clearPendingInsert(sessionId);
  }, [editor, pendingInsert, sessionId, draftActions]);

  // Extract restored attachments from draft on first restore
  const [restoredAttachments, setRestoredAttachments] = useState<
    FileAttachment[]
  >([]);
  useLayoutEffect(() => {
    if (!draft || typeof draft === "string") return;
    const incoming = draft.attachments ?? [];
    // Short-circuit the common empty→empty case to avoid creating a new array
    // reference that would trigger unnecessary re-renders.
    setRestoredAttachments((prev) =>
      prev.length === 0 && incoming.length === 0 ? prev : incoming,
    );
  }, [draft]);

  const attachmentsRef = useRef<FileAttachment[]>([]);

  const saveDraft = useCallback(
    (e: Editor, attachments?: FileAttachment[]) => {
      // Don't save until store has hydrated from storage
      // This prevents overwriting stored drafts with empty content before restoration
      if (!hasHydrated) return;

      if (attachments !== undefined) {
        attachmentsRef.current = attachments;
      }

      const json = e.getJSON();
      const content = tiptapJsonToEditorContent(json);
      const withAttachments: EditorContent =
        attachmentsRef.current.length > 0
          ? { ...content, attachments: attachmentsRef.current }
          : content;
      draftActions.setDraft(
        sessionId,
        isContentEmpty(withAttachments) ? null : withAttachments,
      );
    },
    [sessionId, draftActions, hasHydrated],
  );

  const clearDraft = useCallback(() => {
    attachmentsRef.current = [];
    draftActions.setDraft(sessionId, null);
  }, [sessionId, draftActions]);

  const getContent = useCallback(
    (attachments?: FileAttachment[]): EditorContent => {
      if (!editorRef.current) return { segments: [] };
      const content = tiptapJsonToEditorContent(editorRef.current.getJSON());
      const atts = attachments ?? attachmentsRef.current;
      return atts.length > 0 ? { ...content, attachments: atts } : content;
    },
    [],
  );

  return {
    saveDraft,
    clearDraft,
    getContent,
    restoredAttachments,
  };
}
