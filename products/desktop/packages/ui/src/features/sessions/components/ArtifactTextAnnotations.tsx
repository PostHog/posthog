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
import {
  commentActionAnchorRect,
  installSelectionSettleGate,
} from "./selectionCommentAction";

type HighlightRect = {
  id: string;
  label: string;
  left: number;
  top: number;
  width: number;
  height: number;
  active: boolean;
};

export function textHighlightLabel(comment: ResourceComment): string {
  const user = comment.created_by;
  const author = user
    ? [user.first_name, user.last_name].filter(Boolean).join(" ") || user.email
    : "Unknown user";
  return `Open comment from ${author}`;
}

type TextNodeIndex = {
  text: string;
  entries: Array<{ node: Text; start: number; end: number }>;
};

export function buildTextNodeIndex(root: HTMLElement): TextNodeIndex {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const entries: TextNodeIndex["entries"] = [];
  let text = "";
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const textNode = node as Text;
    const start = text.length;
    text += textNode.data;
    entries.push({ node: textNode, start, end: text.length });
  }
  return { text, entries };
}

export function rangeFromOffsets(
  index: TextNodeIndex,
  start: number,
  end: number,
): Range | null {
  let startNode: Text | null = null;
  let endNode: Text | null = null;
  let startOffset = 0;
  let endOffset = 0;
  for (const entry of index.entries) {
    if (!startNode && start >= entry.start && start <= entry.end) {
      startNode = entry.node;
      startOffset = start - entry.start;
    }
    if (end >= entry.start && end <= entry.end) {
      endNode = entry.node;
      endOffset = end - entry.start;
      break;
    }
  }
  if (!startNode || !endNode) return null;
  const range = document.createRange();
  range.setStart(startNode, startOffset);
  range.setEnd(endNode, endOffset);
  return range;
}

// Range.getClientRects() reports both an inline element's border box and its
// inner text nodes when the element is fully selected (e.g. <strong> inside a
// highlighted line), so translucent highlight rects stack and look doubled.
// Keep only rects not contained by another rect.
function dedupeClientRects(rects: Iterable<DOMRect>): DOMRect[] {
  const EPSILON = 0.5;
  const contains = (outer: DOMRect, inner: DOMRect) =>
    outer.left <= inner.left + EPSILON &&
    outer.right >= inner.right - EPSILON &&
    outer.top <= inner.top + EPSILON &&
    outer.bottom >= inner.bottom - EPSILON;
  const list = Array.from(rects).filter(
    (rect) => rect.width > 0 && rect.height > 0,
  );
  return list.filter(
    (rect, index) =>
      !list.some(
        (other, otherIndex) =>
          otherIndex !== index &&
          contains(other, rect) &&
          // Of two identical rects, keep the first.
          (otherIndex < index || !contains(rect, other)),
      ),
  );
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
  ) => void | Promise<void>;
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
  const textIndexRef = useRef<TextNodeIndex | null>(null);
  const firstRectByThread = useMemo(() => {
    const first = new Map<string, number>();
    rects.forEach((rect, index) => {
      if (!first.has(rect.id)) first.set(rect.id, index);
    });
    return first;
  }, [rects]);

  const clearOverlay = useCallback(() => {
    setSelection(null);
    setPendingAnchor(null);
  }, []);

  const dismiss = useCallback(() => {
    clearOverlay();
    window.getSelection()?.removeAllRanges();
  }, [clearOverlay]);

  const rootComments = useMemo(
    () => comments.filter((comment) => !comment.source_comment),
    [comments],
  );

  const recalculate = useCallback(() => {
    const root = rootRef.current;
    const container = containerRef.current;
    if (!root || !container) return;
    const textIndex = buildTextNodeIndex(root);
    textIndexRef.current = textIndex;
    const text = textIndex.text;
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
      const range = rangeFromOffsets(textIndex, resolved.start, resolved.end);
      if (!range) continue;
      for (const box of dedupeClientRects(range.getClientRects())) {
        nextRects.push({
          id: comment.id,
          label: textHighlightLabel(comment),
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

  useEffect(() => {
    recalculateRef.current = recalculate;
  }, [recalculate]);

  useEffect(() => recalculate(), [recalculate]);

  useEffect(() => {
    const container = containerRef.current;
    const root = rootRef.current;
    if (!container || !root) return;
    let frame = 0;
    const update = () => {
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        recalculateRef.current();
      });
    };
    const observer = new ResizeObserver(update);
    const mutationObserver = new MutationObserver(update);
    observer.observe(root);
    mutationObserver.observe(root, {
      childList: true,
      characterData: true,
      subtree: true,
    });
    window.addEventListener("resize", update);
    container.addEventListener("scroll", update, { passive: true });
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      mutationObserver.disconnect();
      window.removeEventListener("resize", update);
      container.removeEventListener("scroll", update);
    };
  }, [containerRef, rootRef]);

  const handledLocateNonce = useRef<number | null>(null);
  useEffect(() => {
    // Comment-list updates re-run this effect; without the nonce guard a new
    // comment replays the previous locate request and yanks the scroll away.
    if (!locateRequest || handledLocateNonce.current === locateRequest.nonce) {
      return;
    }
    const root = rootRef.current;
    const comment = rootComments.find(({ id }) => id === locateRequest.id);
    const context = comment ? readCommentContext(comment) : null;
    if (!root || context?.anchor.kind !== "text") return;
    const textIndex = buildTextNodeIndex(root);
    const resolved = resolveTextCommentAnchor(textIndex.text, context.anchor);
    if (!resolved) return;
    handledLocateNonce.current = locateRequest.nonce;
    const range = rangeFromOffsets(textIndex, resolved.start, resolved.end);
    const target = range?.startContainer.parentElement;
    target?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [locateRequest, rootComments, rootRef]);

  useEffect(() => {
    const container = containerRef.current;
    const root = rootRef.current;
    if (!container || !root) return;
    let frame = 0;
    const updateSelection = () => {
      const domSelection = window.getSelection();
      if (
        !domSelection ||
        domSelection.isCollapsed ||
        domSelection.rangeCount === 0
      ) {
        if (
          document.activeElement instanceof Element &&
          document.activeElement.closest("[data-selection-comment-overlay]")
        ) {
          return;
        }
        // Only reset local overlay state here: clearing the DOM selection on
        // every collapse would steal the caret from inputs elsewhere in the
        // app and cancel drag-selections as they start.
        clearOverlay();
        return;
      }
      const range = domSelection.getRangeAt(0);
      if (
        !root.contains(range.startContainer) ||
        !root.contains(range.endContainer)
      ) {
        clearOverlay();
        return;
      }
      const offsets = selectionOffsets(root, range);
      const documentText =
        textIndexRef.current?.text ?? buildTextNodeIndex(root).text;
      const anchor = createTextCommentAnchor(
        documentText,
        offsets.start,
        offsets.end,
      );
      if (!anchor) return;
      // Anchor to the selection's end line, where the pointer was released.
      const endRect = commentActionAnchorRect(
        range.getClientRects?.() ?? [],
        range.getBoundingClientRect(),
      );
      setPendingAnchor(anchor);
      setSelection({
        text: anchor.quote,
        fromLine: offsets.start + 1,
        toLine: offsets.end + 1,
        anchor: {
          top: endRect.top,
          endX: endRect.right,
          bottom: endRect.bottom,
        },
      });
    };
    const scheduleUpdate = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(updateSelection);
    };
    const removeGate = installSelectionSettleGate(document, {
      onGestureStart: clearOverlay,
      onSelectionSettled: scheduleUpdate,
      onIdleSelectionChange: scheduleUpdate,
      onGestureCancel: clearOverlay,
    });
    // Hide on scroll because the HTML and canvas surfaces cannot keep a
    // fixed-position host action anchored during an iframe scroll.
    container.addEventListener("scroll", clearOverlay, { passive: true });
    return () => {
      cancelAnimationFrame(frame);
      container.removeEventListener("scroll", clearOverlay);
      removeGate();
    };
  }, [clearOverlay, containerRef, rootRef]);

  return (
    <>
      <div className="pointer-events-none absolute inset-0 z-10">
        {rects.map((rect, index) => (
          <button
            // A selection can span several DOM rectangles, hence the index.
            key={`${rect.id}-${index}`}
            type="button"
            tabIndex={firstRectByThread.get(rect.id) === index ? 0 : -1}
            className={`pointer-events-auto absolute rounded-[2px] ${
              rect.active ? "" : "hover:bg-yellow-300/45"
            }`}
            style={{
              left: rect.left,
              top: rect.top,
              width: rect.width,
              height: rect.height,
              backgroundColor: rect.active
                ? "rgba(250, 204, 21, 0.48)"
                : "rgba(250, 204, 21, 0.32)",
            }}
            onClick={() => onActivateThread(rect.id)}
            aria-label={rect.label}
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
        onSubmit={async (_start, _end, content, mentions) => {
          if (pendingAnchor) await onCreate(pendingAnchor, content, mentions);
        }}
      />
    </>
  );
}
