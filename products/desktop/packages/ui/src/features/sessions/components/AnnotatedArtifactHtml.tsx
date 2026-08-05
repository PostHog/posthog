import type { ResourceComment } from "@posthog/api-client/posthog-client";
import {
  commentAnchorSchema,
  type TextCommentAnchor,
} from "@posthog/core/comments/anchors";
import type { UserBasic } from "@posthog/shared/domain-types";
import type { EditorSelection } from "@posthog/ui/features/code-editor/components/CodeMirrorEditor";
import { SelectionCommentOverlay } from "@posthog/ui/features/code-editor/components/SelectionCommentOverlay";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { artifactHtmlDocument } from "./artifactPreviewDocument";
import {
  type CommentLocateRequest,
  type HighlightResolution,
  readCommentContext,
} from "./commentViewTypes";

const BRIDGE_MARKER = "__POSTHOG_ARTIFACT_COMMENT_BRIDGE__";

type FrameRect = {
  top: number;
  left: number;
  right: number;
  bottom: number;
  width: number;
  height: number;
};

function isFrameRect(value: unknown): value is FrameRect {
  if (!value || typeof value !== "object") return false;
  return ["top", "left", "right", "bottom", "width", "height"].every((key) => {
    const field = (value as Record<string, unknown>)[key];
    return typeof field === "number" && Number.isFinite(field);
  });
}

export function AnnotatedArtifactHtml({
  html,
  name,
  comments,
  activeThreadId,
  locateRequest,
  members,
  onActivateThread,
  onCreate,
  onResolutionsChange,
}: {
  html: string;
  name: string;
  comments: ResourceComment[];
  activeThreadId: string | null;
  locateRequest: CommentLocateRequest | null;
  members: UserBasic[];
  onActivateThread: (id: string) => void;
  onCreate: (
    anchor: TextCommentAnchor,
    content: string,
    mentions?: number[],
  ) => void;
  onResolutionsChange: (resolutions: Map<string, HighlightResolution>) => void;
}) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const channelRef = useRef(`artifact-comments-${crypto.randomUUID()}`);
  const [pendingAnchor, setPendingAnchor] = useState<TextCommentAnchor | null>(
    null,
  );
  const [selection, setSelection] = useState<EditorSelection | null>(null);
  const documentUrl = useMemo(() => {
    const document = artifactHtmlDocument(html, channelRef.current);
    return URL.createObjectURL(new Blob([document], { type: "text/html" }));
  }, [html]);

  useEffect(() => () => URL.revokeObjectURL(documentUrl), [documentUrl]);

  const bridgeItems = useMemo(
    () =>
      comments.flatMap((comment) => {
        if (comment.source_comment) return [];
        const context = readCommentContext(comment);
        return context?.anchor.kind === "text"
          ? [
              {
                id: comment.id,
                anchor: context.anchor,
                active: comment.id === activeThreadId,
              },
            ]
          : [];
      }),
    [activeThreadId, comments],
  );

  const sendComments = useCallback(() => {
    iframeRef.current?.contentWindow?.postMessage(
      {
        marker: BRIDGE_MARKER,
        channel: channelRef.current,
        type: "comments",
        items: bridgeItems,
      },
      "*",
    );
  }, [bridgeItems]);

  useEffect(() => {
    sendComments();
  }, [sendComments]);

  const sendLocate = useCallback(() => {
    if (!locateRequest) return;
    iframeRef.current?.contentWindow?.postMessage(
      {
        marker: BRIDGE_MARKER,
        channel: channelRef.current,
        type: "locate",
        id: locateRequest.id,
      },
      "*",
    );
  }, [locateRequest]);

  useEffect(() => {
    sendLocate();
  }, [sendLocate]);

  const activateThreadRef = useRef(onActivateThread);
  activateThreadRef.current = onActivateThread;
  const resolutionsChangeRef = useRef(onResolutionsChange);
  resolutionsChangeRef.current = onResolutionsChange;
  const sendCommentsRef = useRef(sendComments);
  sendCommentsRef.current = sendComments;
  const sendLocateRef = useRef(sendLocate);
  sendLocateRef.current = sendLocate;

  useEffect(() => {
    const receive = (event: MessageEvent) => {
      if (event.source !== iframeRef.current?.contentWindow) return;
      const data = event.data as Record<string, unknown> | null;
      if (
        !data ||
        data.marker !== BRIDGE_MARKER ||
        data.channel !== channelRef.current
      ) {
        return;
      }
      if (data.type === "ready") {
        sendCommentsRef.current();
        sendLocateRef.current();
        return;
      }
      if (data.type === "activate" && typeof data.id === "string") {
        activateThreadRef.current(data.id);
        return;
      }
      if (data.type === "resolutions" && Array.isArray(data.items)) {
        const resolutions = new Map<string, HighlightResolution>();
        for (const item of data.items) {
          if (!item || typeof item !== "object") continue;
          const { id, status } = item as Record<string, unknown>;
          if (
            typeof id === "string" &&
            (status === "exact" ||
              status === "reanchored" ||
              status === "orphaned")
          ) {
            resolutions.set(id, status);
          }
        }
        resolutionsChangeRef.current(resolutions);
        return;
      }
      if (data.type !== "selection" || !isFrameRect(data.triggerRect)) return;
      const parsed = commentAnchorSchema.safeParse(data.anchor);
      if (!parsed.success || parsed.data.kind !== "text") return;
      const frameBox = iframeRef.current?.getBoundingClientRect();
      if (!frameBox) return;
      setPendingAnchor(parsed.data);
      setSelection({
        text: parsed.data.quote,
        fromLine: parsed.data.start + 1,
        toLine: parsed.data.end + 1,
        anchor: {
          top: frameBox.top + data.triggerRect.bottom,
          left: Math.min(
            frameBox.left + data.triggerRect.right + 6,
            window.innerWidth - 440,
          ),
        },
      });
    };
    window.addEventListener("message", receive);
    return () => window.removeEventListener("message", receive);
  }, []);

  const dismiss = () => {
    setPendingAnchor(null);
    setSelection(null);
  };

  return (
    <div className="relative size-full">
      <iframe
        ref={iframeRef}
        className="size-full border-0 bg-white"
        sandbox="allow-scripts"
        referrerPolicy="no-referrer"
        src={documentUrl}
        title={`Preview of ${name}`}
        onLoad={sendComments}
      />
      <SelectionCommentOverlay
        selection={selection}
        open={!!selection && !!pendingAnchor}
        filePath={name}
        actionLabel="Add comment"
        placeholder="Add a comment about this selection..."
        showActionText
        initiallyExpanded
        members={members}
        onDismiss={dismiss}
        onSubmit={(_start, _end, content, mentions) => {
          if (pendingAnchor) onCreate(pendingAnchor, content, mentions);
          dismiss();
        }}
      />
    </div>
  );
}
