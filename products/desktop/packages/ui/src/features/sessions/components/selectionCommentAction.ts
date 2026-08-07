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
  hoverShadow: string;
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
    background: "#eceee8",
    color: "#0d0d0d",
    border: "#cbd0c3",
    hoverBackground: "#d8dbd1",
    shadow: "0 1px 2px rgba(0,0,0,0.08),0 4px 12px rgba(0,0,0,0.12)",
    hoverShadow: "0 2px 4px rgba(0,0,0,0.1),0 6px 16px rgba(0,0,0,0.16)",
  },
  dark: {
    background: "#18181f",
    color: "#e6e6e6",
    border: "#2a2a37",
    hoverBackground: "#24243e",
    shadow: "0 1px 2px rgba(0,0,0,0.5),0 4px 12px rgba(0,0,0,0.5)",
    hoverShadow: "0 2px 4px rgba(0,0,0,0.5),0 6px 16px rgba(0,0,0,0.65)",
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
  return `--ph-comment-action-bg:${palette.background};--ph-comment-action-fg:${palette.color};--ph-comment-action-border:${palette.border};--ph-comment-action-hover:${palette.hoverBackground};--ph-comment-action-shadow:${palette.shadow};--ph-comment-action-hover-shadow:${palette.hoverShadow};`;
}

// A neutral pill that reads as a card floating above the content: solid themed
// background (nothing bleeds through), visible hover feedback, pointer cursor.
export function commentActionButtonCss(): string {
  return `.ph-comment-action-button{position:fixed;z-index:2147483647;display:flex;align-items:center;gap:6px;height:30px;padding:0 12px;border:1px solid var(--ph-comment-action-border);border-radius:999px;background:var(--ph-comment-action-bg);color:var(--ph-comment-action-fg);font:600 12px/1 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;box-shadow:var(--ph-comment-action-shadow);cursor:pointer;user-select:none;transition:background-color .12s,box-shadow .12s}.ph-comment-action-button:hover{background:var(--ph-comment-action-hover);box-shadow:var(--ph-comment-action-hover-shadow)}.ph-comment-action-button:focus-visible{outline:2px solid var(--ph-comment-action-border);outline-offset:2px}.ph-comment-action-button svg{flex:none}`;
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
  style.setProperty("--ph-comment-action-hover-shadow", palette.hoverShadow);
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
