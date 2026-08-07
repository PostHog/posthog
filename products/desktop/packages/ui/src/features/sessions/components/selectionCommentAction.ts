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
};

// Neutral card colors so the action doesn't compete with the comment
// highlight color behind the selection. The values are hardcoded because they
// run inside opaque-origin sandbox iframes where the app's CSS variable tokens
// don't exist.
export const COMMENT_ACTION_BUTTON_THEMES: Record<
  CommentSurfaceTheme,
  CommentActionButtonTheme
> = {
  light: {
    background: "#ffffff",
    color: "#1f2328",
    border: "rgba(31, 35, 40, 0.16)",
    hoverBackground: "#f5f5f4",
  },
  dark: {
    background: "#2b2b2e",
    color: "#fafafa",
    border: "rgba(255, 255, 255, 0.16)",
    hoverBackground: "#3f3f43",
  },
};

// CSS variables let the host flip the theme of an already-running iframe
// document with a `theme` message instead of rebuilding (and reloading) it.
export function commentActionButtonCssVars(theme: CommentSurfaceTheme): string {
  const palette = COMMENT_ACTION_BUTTON_THEMES[theme];
  return `--ph-comment-action-bg:${palette.background};--ph-comment-action-fg:${palette.color};--ph-comment-action-border:${palette.border};--ph-comment-action-hover:${palette.hoverBackground};`;
}

export function commentActionButtonCss(): string {
  return `.ph-comment-action-button{position:fixed;z-index:2147483647;display:flex;align-items:center;gap:6px;height:34px;padding:0 13px;border:1px solid var(--ph-comment-action-border);border-radius:8px;background:var(--ph-comment-action-bg);color:var(--ph-comment-action-fg);font:500 13px/1 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;box-shadow:0 3px 12px rgba(0,0,0,.18);cursor:pointer}.ph-comment-action-button:hover{background:var(--ph-comment-action-hover)}`;
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
