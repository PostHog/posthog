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
  target: HTMLElement,
): void {
  const palette = themes[theme] || themes.light;
  if (!palette) return;
  const style = target.style;
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
// selecting. Check boxes from visually last to first and take the first leaf
// box, which avoids scanning every pair for normal selections.
export function commentActionAnchorRect<T extends CommentActionBox>(
  rects: ArrayLike<T>,
  fallback: T,
): T {
  const boxes: T[] = [];
  for (let index = 0; index < rects.length; index++) {
    const rect = rects[index];
    if (rect.width > 0 || rect.height > 0) {
      boxes.push(rect);
    }
  }
  if (boxes.length === 0) {
    return fallback;
  }
  const EPSILON = 0.5;
  const area = (box: T) => box.width * box.height;
  const encloses = (outer: T, inner: T) =>
    area(outer) > area(inner) + 1 &&
    outer.left <= inner.left + EPSILON &&
    outer.right >= inner.right - EPSILON &&
    outer.top <= inner.top + EPSILON &&
    outer.bottom >= inner.bottom - EPSILON;
  const candidates = boxes.slice().sort((left, right) => {
    const verticalDistance = right.bottom - left.bottom;
    return Math.abs(verticalDistance) > EPSILON
      ? verticalDistance
      : right.right - left.right;
  });
  for (const box of candidates) {
    if (!boxes.some((other) => other !== box && encloses(box, other))) {
      return box;
    }
  }
  return candidates[0];
}

// Where the floating action or composer sits relative to the selection's end
// line. Actions center on the caret line; composers sit below it. When the
// right edge has no room, the element stays aligned to the caret; near the
// viewport bottom it flips above the line.
export function computeCommentActionPlacement(
  rect: { top: number; right: number; bottom: number },
  bounds: { width: number; height: number },
  action: { width: number; height: number },
  alignment: "center" | "below" = "center",
): { top: number; left: number } {
  const MARGIN = 8;
  const lineMiddle = rect.top + (rect.bottom - rect.top) / 2;
  let left = rect.right + MARGIN;
  let top =
    alignment === "below" ? rect.bottom + 6 : lineMiddle - action.height / 2;
  const shouldDropBelow = left + action.width > bounds.width - MARGIN;
  if (shouldDropBelow) {
    left = Math.max(rect.right - action.width, MARGIN);
    if (alignment === "center") top = rect.bottom + 6;
  }
  if (
    (alignment === "below" || shouldDropBelow) &&
    top + action.height > bounds.height - MARGIN
  ) {
    top = rect.top - action.height - 6;
  }
  const maxLeft = Math.max(bounds.width - action.width - MARGIN, MARGIN);
  const maxTop = Math.max(bounds.height - action.height - MARGIN, MARGIN);
  return {
    left: Math.min(Math.max(left, MARGIN), maxLeft),
    top: Math.min(Math.max(top, MARGIN), maxTop),
  };
}

export type SelectionSettleGateCallbacks = {
  // A selection gesture started outside the action UI; hide any visual
  // anchored to the selection.
  onGestureStart?: () => void;
  // The gesture finished and the browser has committed the range; re-read the
  // selection, it is final.
  onSelectionSettled?: () => void;
  // Selection changed outside a gesture (programmatic, or a click that
  // collapsed it).
  onIdleSelectionChange?: () => void;
  // Gesture interrupted before it finished (pointercancel, window blur).
  onGestureCancel?: () => void;
};

// While the user selects, the range keeps moving, so an action anchored to the
// live selection chases the cursor. The gate reports only settled selections,
// following the pattern the editor toolbars converged on:
//
//   selectstart / pointerdown / selection keydown -> hide
//   selectionchange                               -> ignore while gesturing
//   pointerup / selection keyup                   -> report, two frames later
//   pointercancel / blur                          -> cancel
//
// The two frames matter: the browser commits the selection AFTER the pointerup
// handler runs, so reading it synchronously returns the mid-gesture range and
// anchors the action to the wrong place. Presses inside the action UI are
// ignored so using the action can't start a gesture.
export function installSelectionSettleGate(
  doc: Document,
  callbacks: SelectionSettleGateCallbacks,
): () => void {
  const view = doc.defaultView;
  let selecting = false;
  let keyGesture = false;
  let frame = 0;

  // Keys that move or extend a selection. "a" only counts with a modifier, so
  // typing the letter doesn't read as select-all.
  const isSelectionKey = (event: KeyboardEvent) => {
    if (event.key === "a" || event.key === "A") {
      return event.metaKey || event.ctrlKey;
    }
    return (
      event.key === "Shift" ||
      event.key === "Home" ||
      event.key === "End" ||
      event.key === "PageUp" ||
      event.key === "PageDown" ||
      event.key.startsWith("Arrow")
    );
  };

  const cancelFrame = () => {
    if (frame && view?.cancelAnimationFrame) {
      view.cancelAnimationFrame(frame);
    }
    frame = 0;
  };
  const settle = () => {
    cancelFrame();
    const request = view?.requestAnimationFrame;
    if (!request) {
      callbacks.onSelectionSettled?.();
      return;
    }
    frame = request.call(view, () => {
      frame = request.call(view, () => {
        frame = 0;
        callbacks.onSelectionSettled?.();
      });
    });
  };
  const inActionUi = (target: EventTarget | null) =>
    target instanceof Element &&
    !!target.closest("[data-selection-comment-overlay]");
  const startGesture = () => {
    if (selecting) {
      return;
    }
    selecting = true;
    cancelFrame();
    callbacks.onGestureStart?.();
  };
  const cancelGesture = () => {
    if (!selecting) {
      return;
    }
    selecting = false;
    keyGesture = false;
    cancelFrame();
    callbacks.onGestureCancel?.();
  };

  const onPointerDown = (event: Event) => {
    // Secondary buttons open menus; they don't select.
    if (event instanceof MouseEvent && event.button > 0) {
      return;
    }
    if (inActionUi(event.target)) {
      return;
    }
    startGesture();
  };
  // Catches drags whose pointerdown we never saw, and keyboard selections.
  const onSelectStart = (event: Event) => {
    if (inActionUi(event.target)) {
      return;
    }
    startGesture();
  };
  const onPointerUp = (event: Event) => {
    if (event instanceof MouseEvent && event.button > 0) {
      return;
    }
    if (!selecting) {
      return;
    }
    selecting = false;
    keyGesture = false;
    settle();
  };
  const onKeyDown = (event: KeyboardEvent) => {
    if (inActionUi(event.target) || !isSelectionKey(event)) {
      return;
    }
    keyGesture = true;
    startGesture();
  };
  const onKeyUp = () => {
    if (!selecting || !keyGesture) {
      return;
    }
    selecting = false;
    keyGesture = false;
    settle();
  };
  const onSelectionChange = () => {
    if (selecting) {
      return;
    }
    callbacks.onIdleSelectionChange?.();
  };

  doc.addEventListener("pointerdown", onPointerDown, true);
  doc.addEventListener("selectstart", onSelectStart, true);
  doc.addEventListener("pointerup", onPointerUp, true);
  doc.addEventListener("pointercancel", cancelGesture, true);
  doc.addEventListener("keydown", onKeyDown, true);
  doc.addEventListener("keyup", onKeyUp, true);
  doc.addEventListener("selectionchange", onSelectionChange);
  view?.addEventListener("blur", cancelGesture);
  return () => {
    cancelFrame();
    doc.removeEventListener("pointerdown", onPointerDown, true);
    doc.removeEventListener("selectstart", onSelectStart, true);
    doc.removeEventListener("pointerup", onPointerUp, true);
    doc.removeEventListener("pointercancel", cancelGesture, true);
    doc.removeEventListener("keydown", onKeyDown, true);
    doc.removeEventListener("keyup", onKeyUp, true);
    doc.removeEventListener("selectionchange", onSelectionChange);
    view?.removeEventListener("blur", cancelGesture);
  };
}
