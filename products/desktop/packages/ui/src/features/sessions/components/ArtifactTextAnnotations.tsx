import type { ResourceComment } from "@posthog/api-client/posthog-client";
import {
  createTextCommentAnchor,
  resolveTextCommentAnchor,
  type TextCommentAnchor,
} from "@posthog/core/comments/anchors";
import type { UserBasic } from "@posthog/shared/domain-types";
import type { EditorSelection } from "@posthog/ui/features/code-editor/components/CodeMirrorEditor";
import { SelectionCommentOverlay } from "@posthog/ui/features/code-editor/components/SelectionCommentOverlay";
import {
  type RefObject,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  type CommentLocateRequest,
  type HighlightResolution,
  readCommentContext,
} from "./commentViewTypes";

type HighlightRect = {
  id: string;
  left: number;
  top: number;
  width: number;
  height: number;
  active: boolean;
};

function rangeFromOffsets(
  root: HTMLElement,
  start: number,
  end: number,
): Range | null {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let offset = 0;
  let startNode: Text | null = null;
  let endNode: Text | null = null;
  let startOffset = 0;
  let endOffset = 0;
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const text = node as Text;
    const next = offset + text.data.length;
    if (!startNode && start >= offset && start <= next) {
      startNode = text;
      startOffset = start - offset;
    }
    if (end >= offset && end <= next) {
      endNode = text;
      endOffset = end - offset;
      break;
    }
    offset = next;
  }
  if (!startNode || !endNode) return null;
  const range = document.createRange();
  range.setStart(startNode, startOffset);
  range.setEnd(endNode, endOffset);
  return range;
}

function selectionOffsets(root: HTMLElement, range: Range) {
  const before = document.createRange();
  before.selectNodeContents(root);
  before.setEnd(range.startContainer, range.startOffset);
  const through = document.createRange();
  through.selectNodeContents(root);
  through.setEnd(range.endContainer, range.endOffset);
  return { start: before.toString().length, end: through.toString().length };
}

interface ArtifactTextAnnotationsProps {
  artifactName: string;
  rootRef: RefObject<HTMLElement | null>;
  containerRef: RefObject<HTMLElement | null>;
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
}

export function ArtifactTextAnnotations({
  artifactName,
  rootRef,
  containerRef,
  comments,
  activeThreadId,
  locateRequest,
  members,
  onActivateThread,
  onCreate,
  onResolutionsChange,
}: ArtifactTextAnnotationsProps) {
  const [selection, setSelection] = useState<EditorSelection | null>(null);
  const [pendingAnchor, setPendingAnchor] = useState<TextCommentAnchor | null>(
    null,
  );
  const [rects, setRects] = useState<HighlightRect[]>([]);

  const rootComments = useMemo(
    () => comments.filter((comment) => !comment.source_comment),
    [comments],
  );

  const recalculate = useCallback(() => {
    const root = rootRef.current;
    const container = containerRef.current;
    if (!root || !container) return;
    const text = root.textContent ?? "";
    const containerBox = container.getBoundingClientRect();
    const nextRects: HighlightRect[] = [];
    const resolutions = new Map<string, HighlightResolution>();

    for (const comment of rootComments) {
      const context = readCommentContext(comment);
      if (!context || context.anchor.kind !== "text") continue;
      const resolved = resolveTextCommentAnchor(text, context.anchor);
      if (!resolved) {
        resolutions.set(comment.id, "orphaned");
        continue;
      }
      resolutions.set(comment.id, resolved.status);
      const range = rangeFromOffsets(root, resolved.start, resolved.end);
      if (!range) continue;
      for (const box of range.getClientRects()) {
        nextRects.push({
          id: comment.id,
          left: box.left - containerBox.left + container.scrollLeft,
          top: box.top - containerBox.top + container.scrollTop,
          width: box.width,
          height: box.height,
          active: comment.id === activeThreadId,
        });
      }
    }
    setRects(nextRects);
    onResolutionsChange(resolutions);
  }, [
    activeThreadId,
    containerRef,
    onResolutionsChange,
    rootComments,
    rootRef,
  ]);

  const recalculateRef = useRef(recalculate);
  recalculateRef.current = recalculate;

  useEffect(() => {
    recalculateRef.current();
    const container = containerRef.current;
    const root = rootRef.current;
    if (!container || !root) return;
    const update = () => recalculateRef.current();
    const observer = new ResizeObserver(update);
    observer.observe(root);
    window.addEventListener("resize", update);
    container.addEventListener("scroll", update, { passive: true });
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", update);
      container.removeEventListener("scroll", update);
    };
  }, [containerRef, rootRef]);

  useEffect(() => {
    if (!locateRequest) return;
    const root = rootRef.current;
    const comment = rootComments.find(({ id }) => id === locateRequest.id);
    const context = comment ? readCommentContext(comment) : null;
    if (!root || context?.anchor.kind !== "text") return;
    const resolved = resolveTextCommentAnchor(
      root.textContent ?? "",
      context.anchor,
    );
    if (!resolved) return;
    const range = rangeFromOffsets(root, resolved.start, resolved.end);
    const target = range?.startContainer.parentElement;
    target?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [locateRequest, rootComments, rootRef]);

  useEffect(() => {
    const container = containerRef.current;
    const root = rootRef.current;
    if (!container || !root) return;
    const handleMouseUp = () => {
      const domSelection = window.getSelection();
      if (
        !domSelection ||
        domSelection.isCollapsed ||
        domSelection.rangeCount === 0
      ) {
        return;
      }
      const range = domSelection.getRangeAt(0);
      if (
        !root.contains(range.startContainer) ||
        !root.contains(range.endContainer)
      ) {
        return;
      }
      const offsets = selectionOffsets(root, range);
      const anchor = createTextCommentAnchor(
        root.textContent ?? "",
        offsets.start,
        offsets.end,
      );
      if (!anchor) return;
      const box = range.getBoundingClientRect();
      setPendingAnchor(anchor);
      setSelection({
        text: anchor.quote,
        fromLine: offsets.start + 1,
        toLine: offsets.end + 1,
        anchor: {
          top: box.bottom,
          left: Math.min(box.right, window.innerWidth - 440),
        },
      });
    };
    container.addEventListener("mouseup", handleMouseUp);
    return () => container.removeEventListener("mouseup", handleMouseUp);
  }, [containerRef, rootRef]);

  const dismiss = useCallback(() => {
    setSelection(null);
    setPendingAnchor(null);
    window.getSelection()?.removeAllRanges();
  }, []);

  return (
    <>
      <div className="pointer-events-none absolute inset-0 z-10" aria-hidden>
        {rects.map((rect, index) => (
          <button
            // A selection can span several DOM rectangles, hence the index.
            key={`${rect.id}-${index}`}
            type="button"
            tabIndex={-1}
            className={`pointer-events-auto absolute rounded-[2px] ${
              rect.active
                ? "bg-yellow-400/55 ring-2 ring-yellow-500"
                : "bg-yellow-300/35 hover:bg-yellow-300/55"
            }`}
            style={{
              left: rect.left,
              top: rect.top,
              width: rect.width,
              height: rect.height,
            }}
            onClick={() => onActivateThread(rect.id)}
            aria-label="Open comment thread"
          />
        ))}
      </div>
      <SelectionCommentOverlay
        selection={selection}
        open={!!selection && !!pendingAnchor}
        filePath={artifactName}
        actionLabel="Add comment"
        placeholder="Add a comment about this selection..."
        showActionText
        members={members}
        onDismiss={dismiss}
        onSubmit={(_start, _end, content, mentions) => {
          if (pendingAnchor) onCreate(pendingAnchor, content, mentions);
          dismiss();
        }}
      />
    </>
  );
}
