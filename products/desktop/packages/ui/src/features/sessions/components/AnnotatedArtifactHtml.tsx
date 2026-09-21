import type { ResourceComment } from "@posthog/api-client/posthog-client";
import {
  commentAnchorSchema,
  type TextCommentAnchor,
} from "@posthog/core/comments/anchors";
import type { UserBasic } from "@posthog/shared/domain-types";
import type { EditorSelection } from "@posthog/ui/features/code-editor/components/CodeMirrorEditor";
import { SelectionCommentOverlay } from "@posthog/ui/features/code-editor/components/SelectionCommentOverlay";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { useThemeStore } from "@posthog/ui/shell/themeStore";
import { parseHttpsUrl } from "@posthog/ui/utils/posthogLinks";
import { useCallback, useMemo, useRef, useState } from "react";
import {
  selectionAnchor,
  withSelectionPosition,
} from "./artifactHtmlCommentPosition";
import { ArtifactHtmlFrame } from "./artifactHtmlFrame";
import {
  ARTIFACT_HTML_BRIDGE_MARKER,
  type ArtifactHtmlFrameRect,
} from "./artifactHtmlFrameHost";
import {
  artifactHtmlDocument,
  scriptedArtifactHtmlDocument,
} from "./artifactPreviewDocument";
import {
  type CommentLocateRequest,
  type HighlightResolution,
  readCommentContext,
} from "./commentViewTypes";
import type { CommentSurfaceTheme } from "./selectionCommentAction";

function isFrameRect(value: unknown): value is ArtifactHtmlFrameRect {
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
  ) => void | Promise<void>;
  onResolutionsChange: (resolutions: Map<string, HighlightResolution>) => void;
}) {
  const channelRef = useRef(`artifact-comments-${crypto.randomUUID()}`);
  const theme = useThemeStore(
    (s): CommentSurfaceTheme => (s.isDarkMode ? "dark" : "light"),
  );
  // Baked into the document at mount; live theme changes ride the `theme`
  // message below so a flip doesn't tear down and reload the running preview.
  const initialTheme = useRef(theme).current;
  const [pendingAnchor, setPendingAnchor] = useState<TextCommentAnchor | null>(
    null,
  );
  const [selection, setSelection] = useState<EditorSelection | null>(null);
  const previewDocument = useMemo(
    () => scriptedArtifactHtmlDocument(html, channelRef.current, initialTheme),
    [html, initialTheme],
  );
  const fallbackDocument = useMemo(
    () => artifactHtmlDocument(html, channelRef.current, initialTheme),
    [html, initialTheme],
  );

  const selectionOpen = selection !== null;
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

  const messages = useMemo(() => {
    const next: Record<string, unknown>[] = [
      {
        marker: ARTIFACT_HTML_BRIDGE_MARKER,
        channel: channelRef.current,
        type: "theme",
        theme,
      },
      {
        marker: ARTIFACT_HTML_BRIDGE_MARKER,
        channel: channelRef.current,
        type: "comments",
        items: bridgeItems,
      },
    ];
    if (!selectionOpen) {
      next.push({
        marker: ARTIFACT_HTML_BRIDGE_MARKER,
        channel: channelRef.current,
        type: "selection-dismissed",
      });
    }
    if (locateRequest) {
      next.push({
        marker: ARTIFACT_HTML_BRIDGE_MARKER,
        channel: channelRef.current,
        type: "locate",
        id: locateRequest.id,
        nonce: locateRequest.nonce,
      });
    }
    return next;
  }, [bridgeItems, locateRequest, selectionOpen, theme]);

  const receive = useCallback(
    (value: unknown, frameBox: ArtifactHtmlFrameRect) => {
      const data = value as Record<string, unknown> | null;
      if (
        !data ||
        data.marker !== ARTIFACT_HTML_BRIDGE_MARKER ||
        data.channel !== channelRef.current
      ) {
        return;
      }
      if (data.type === "activate" && typeof data.id === "string") {
        onActivateThread(data.id);
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
        onResolutionsChange(resolutions);
        return;
      }
      if (data.type === "selection-position" && isFrameRect(data.rect)) {
        const rect = data.rect;
        setSelection((current) =>
          withSelectionPosition(current, frameBox, rect),
        );
        return;
      }
      if (data.type !== "selection" || !isFrameRect(data.rect)) return;
      const parsed = commentAnchorSchema.safeParse(data.anchor);
      if (!parsed.success || parsed.data.kind !== "text") return;
      setPendingAnchor(parsed.data);
      setSelection({
        text: parsed.data.quote,
        fromLine: parsed.data.start + 1,
        toLine: parsed.data.end + 1,
        anchor: selectionAnchor(frameBox, data.rect),
      });
    },
    [onActivateThread, onResolutionsChange],
  );

  const openExternal = useCallback((href: string) => {
    const url = parseHttpsUrl(href);
    if (url) openExternalUrl(url.href);
  }, []);

  const dismiss = () => {
    setPendingAnchor(null);
    setSelection(null);
  };

  return (
    <div className="relative size-full">
      <ArtifactHtmlFrame
        document={previewDocument}
        fallbackDocument={fallbackDocument}
        name={name}
        messages={messages}
        onMessage={receive}
        onOpenExternal={openExternal}
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
        onSubmit={async (_start, _end, content, mentions) => {
          if (pendingAnchor) await onCreate(pendingAnchor, content, mentions);
        }}
      />
    </div>
  );
}
