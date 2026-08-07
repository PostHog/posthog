// Shared behavior + look for the floating "Comment" action shown next to a
// text selection. Every surface (artifact annotations, HTML artifact bridge,
// canvas sandbox) wires the same pieces instead of re-implementing them:
// surfaces rendered into sandboxed iframes inject this module's functions via
// .toString(), so those must stay dependency-free and reference no imports.

export type CommentSurfaceTheme = "light" | "dark";

type CommentActionButtonTheme = {
  background: string;
  color: string;
  border: string;
  hoverBackground: string;
  shadow: string;
};

// Neutral card colors so the action doesn't compete with the comment
// highlight color behind the selection. The values mirror the app's gray
// tokens (gray-2 bg, gray-5 border, gray-4 hover) and are hardcoded because
// they run inside opaque-origin sandbox iframes where the app's CSS variable
// tokens don't exist.
export const COMMENT_ACTION_BUTTON_THEMES: Record<
  CommentSurfaceTheme,
  CommentActionButtonTheme
> = {
  light: {
    background: "#ffffff",
    color: "#1b1d1a",
    border: "#cbd0c3",
    hoverBackground: "#eceee8",
    shadow: "0 1px 2px rgba(0,0,0,0.10),0 2px 6px rgba(0,0,0,0.08)",
  },
  dark: {
    background: "#24242e",
    color: "#e6e6e6",
    border: "#3a3a4c",
    hoverBackground: "#31313f",
    shadow: "0 1px 2px rgba(0,0,0,0.45),0 2px 6px rgba(0,0,0,0.35)",
  },
};

// Bold-weight chat bubble (Phosphor ChatCircle), so the iframed action carries
// the same icon the in-app buttons render with @phosphor-icons/react.
export const COMMENT_ACTION_ICON_SVG =
  '<svg width="14" height="14" viewBox="0 0 256 256" fill="currentColor" aria-hidden="true"><path d="M128,20A108,108,0,0,0,31.85,177.23L21,209.66A20,20,0,0,0,46.34,235l32.43-10.81A108,108,0,1,0,128,20Zm0,192a84,84,0,0,1-42.06-11.27,12,12,0,0,0-6-1.62,12.1,12.1,0,0,0-3.8.62l-29.79,9.93,9.93-29.79a12,12,0,0,0-1-9.81A84,84,0,1,1,128,212Z"/></svg>';

// CSS variables let the host flip the theme of an already-running iframe
// document with a `theme` message instead of rebuilding (and reloading) it.
export function commentActionButtonCssVars(theme: CommentSurfaceTheme): string {
  const palette = COMMENT_ACTION_BUTTON_THEMES[theme];
  return `--ph-comment-action-bg:${palette.background};--ph-comment-action-fg:${palette.color};--ph-comment-action-border:${palette.border};--ph-comment-action-hover:${palette.hoverBackground};--ph-comment-action-shadow:${palette.shadow};`;
}

// The one comment action look, shared by every surface: the app renders this
// class directly and the sandboxed iframes inject the same rules, so a markdown
// artifact, an HTML artifact and a canvas cannot drift apart. Solid themed
// background (nothing bleeds through), background-only hover (no shadow jump),
// pointer cursor.
export function commentActionButtonCss(): string {
  return `.ph-comment-action-button{position:fixed;z-index:2147483647;display:inline-flex;align-items:center;gap:6px;height:28px;padding:0 10px;margin:0;border:1px solid var(--ph-comment-action-border);border-radius:8px;background:var(--ph-comment-action-bg);color:var(--ph-comment-action-fg);font:500 12px/1 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;box-shadow:var(--ph-comment-action-shadow);cursor:pointer;user-select:none;-webkit-user-select:none;transition:background-color .1s ease}.ph-comment-action-button:hover{background:var(--ph-comment-action-hover)}.ph-comment-action-button:active{background:var(--ph-comment-action-hover)}.ph-comment-action-button:focus-visible{outline:2px solid var(--ph-comment-action-border);outline-offset:2px}.ph-comment-action-button--icon{width:28px;padding:0;justify-content:center}.ph-comment-action-button svg{flex:none;display:block}`;
}

// Dependency-free: injected into iframe bridge scripts via .toString() and
// called with the baked-in COMMENT_ACTION_BUTTON_THEMES.
export function setCommentActionTheme(
  theme: string,
  themes: Record<string, CommentActionButtonTheme>,
): void {
  const palette = themes[theme] || themes.light;
  if (!palette) return;
  const style = document.documentElement.style;
  style.setProperty("--ph-comment-action-bg", palette.background);
  style.setProperty("--ph-comment-action-fg", palette.color);
  style.setProperty("--ph-comment-action-border", palette.border);
  style.setProperty("--ph-comment-action-hover", palette.hoverBackground);
  style.setProperty("--ph-comment-action-shadow", palette.shadow);
}

type CommentActionBox = {
  top: number;
  right: number;
  bottom: number;
  left: number;
  width: number;
  height: number;
};

// Which box the action anchors to. A Range spanning block elements reports the
// wrapper boxes (paragraph, blockquote, list) alongside the text line boxes, so
// neither the bounding box nor the last entry marks where the user stopped
// selecting. Keep the leaf boxes — those that enclose no other box — and take
// the visually lowest, then right-most one: the end of the last selected line.
export function commentActionAnchorRect<T extends CommentActionBox>(
  rects: ArrayLike<T>,
  fallback: T,
): T {
  const boxes: T[] = [];
  for (let index = 0; index < rects.length; index++) {
    const rect = rects[index];
    if (rect.width > 0 || rect.height > 0) boxes.push(rect);
  }
  if (boxes.length === 0) return fallback;
  const EPSILON = 0.5;
  const area = (box: T) => box.width * box.height;
  const encloses = (outer: T, inner: T) =>
    area(outer) > area(inner) + 1 &&
    outer.left <= inner.left + EPSILON &&
    outer.right >= inner.right - EPSILON &&
    outer.top <= inner.top + EPSILON &&
    outer.bottom >= inner.bottom - EPSILON;
  const leaves = boxes.filter(
    (box) => !boxes.some((other) => other !== box && encloses(box, other)),
  );
  const pool = leaves.length > 0 ? leaves : boxes;
  let best = pool[0];
  for (const box of pool) {
    const lower = box.bottom > best.bottom + EPSILON;
    const sameLine = Math.abs(box.bottom - best.bottom) <= EPSILON;
    if (lower || (sameLine && box.right > best.right)) best = box;
  }
  return best;
}

// Where the action sits relative to the selection's end line (Google Docs
// style): just right of the caret, vertically centered on the line. When the
// right edge has no room it drops below the end line instead, keeping its
// right edge at the caret; near the viewport bottom it flips above the line.
// `rect` is the selection's end line, `bounds` the viewport/container, `action`
// the action element's measured size.
export function computeCommentActionPlacement(
  rect: { top: number; right: number; bottom: number },
  bounds: { width: number; height: number },
  action: { width: number; height: number },
): { top: number; left: number } {
  const MARGIN = 8;
  const lineMiddle = rect.top + (rect.bottom - rect.top) / 2;
  let left = rect.right + MARGIN;
  let top = lineMiddle - action.height / 2;
  if (left + action.width > bounds.width - MARGIN) {
    left = Math.max(rect.right - action.width, MARGIN);
    top = rect.bottom + 6;
    if (top + action.height > bounds.height - MARGIN) {
      top = rect.top - action.height - 6;
    }
  }
  const maxLeft = Math.max(bounds.width - action.width - MARGIN, MARGIN);
  const maxTop = Math.max(bounds.height - action.height - MARGIN, MARGIN);
  return {
    left: Math.min(Math.max(left, MARGIN), maxLeft),
    top: Math.min(Math.max(top, MARGIN), maxTop),
  };
}

export type SelectionSettleGateCallbacks = {
  // Pointer pressed outside the action UI; hide any visual anchored to the
  // selection.
  onGestureStart?: () => void;
  // Pointer released after a gesture; re-read the selection, it is final.
  onSelectionSettled?: () => void;
  // Selection changed with no pointer down (keyboard, programmatic).
  onIdleSelectionChange?: () => void;
  // Gesture interrupted before pointerup (window blur).
  onGestureCancel?: () => void;
};

// While the user drag-selects, the range keeps moving, so an action anchored
// to the live selection visibly chases the cursor. The gate suppresses
// selection reporting during the drag and reports the final range on
// pointerup. Clicks inside the action UI are excluded so pressing the action
// itself doesn't restart a gesture.
export function installSelectionSettleGate(
  doc: Document,
  callbacks: SelectionSettleGateCallbacks,
): () => void {
  let dragging = false;
  const onPointerDown = (event: Event) => {
    if (
      event.target instanceof Element &&
      event.target.closest("[data-selection-comment-overlay]")
    ) {
      return;
    }
    dragging = true;
    callbacks.onGestureStart?.();
  };
  const settle = () => {
    if (!dragging) return;
    dragging = false;
    callbacks.onSelectionSettled?.();
  };
  const cancel = () => {
    if (!dragging) return;
    dragging = false;
    callbacks.onGestureCancel?.();
  };
  const onSelectionChange = () => {
    if (dragging) return;
    callbacks.onIdleSelectionChange?.();
  };
  doc.addEventListener("pointerdown", onPointerDown, true);
  doc.addEventListener("pointerup", settle, true);
  doc.addEventListener("pointercancel", settle, true);
  doc.addEventListener("selectionchange", onSelectionChange);
  doc.defaultView?.addEventListener("blur", cancel);
  return () => {
    doc.removeEventListener("pointerdown", onPointerDown, true);
    doc.removeEventListener("pointerup", settle, true);
    doc.removeEventListener("pointercancel", settle, true);
    doc.removeEventListener("selectionchange", onSelectionChange);
    doc.defaultView?.removeEventListener("blur", cancel);
  };
}
