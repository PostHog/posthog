import {
  resolveTextCommentAnchor,
  type TextCommentAnchor,
} from "@posthog/core/comments/anchors";
import {
  COMMENT_ACTION_BUTTON_THEMES,
  COMMENT_ACTION_ICON_SVG,
  type CommentSurfaceTheme,
  commentActionAnchorRect,
  commentActionButtonCss,
  computeCommentActionPlacement,
  installSelectionSettleGate,
  setCommentActionTheme,
} from "./selectionCommentAction";

const BRIDGE_MARKER = "__POSTHOG_ARTIFACT_COMMENT_BRIDGE__";

type BridgeComment = {
  id: string;
  anchor: TextCommentAnchor;
  active?: boolean;
};

type BridgeRect = {
  top: number;
  left: number;
  right: number;
  bottom: number;
  width: number;
  height: number;
};

type BridgeSelectionMessage = {
  anchor: TextCommentAnchor;
  rect: BridgeRect;
  triggerRect: BridgeRect;
};

type BridgeRuntimeOptions = {
  channel: string;
  marker: string;
  initialTheme: CommentSurfaceTheme;
  themes: typeof COMMENT_ACTION_BUTTON_THEMES;
  actionIcon: string;
  buttonCss: string;
  setActionTheme: typeof setCommentActionTheme;
  placeAction: typeof computeCommentActionPlacement;
  anchorRect: typeof commentActionAnchorRect;
  resolveAnchor: typeof resolveTextCommentAnchor;
  installSelectionSettleGate: typeof installSelectionSettleGate;
};

// This function is serialized into the isolated artifact document. Keep it
// self-contained and pass every external dependency through options.
function runArtifactHtmlCommentBridge({
  channel,
  marker,
  initialTheme,
  themes,
  actionIcon,
  buttonCss,
  setActionTheme: applyActionTheme,
  placeAction,
  anchorRect,
  resolveAnchor,
  installSelectionSettleGate: installSettleGate,
}: BridgeRuntimeOptions): void {
  const HighlightConstructor = window.Highlight;
  const css = Reflect.get(window, "CSS") as typeof CSS | undefined;
  const highlightRegistry = css?.highlights;
  const state = {
    button: null as HTMLButtonElement | null,
    action: null as { message: BridgeSelectionMessage; range: Range } | null,
    activeRange: null as Range | null,
    selectionTimer: 0,
    renderTimer: 0,
    positionFrame: 0,
    locateNonce: null as number | null,
    entries: [] as Array<{ id: string; range: Range }>,
    items: [] as BridgeComment[],
    theme: initialTheme as string,
  };

  document.currentScript?.remove();

  const send = (type: string, payload: Record<string, unknown> = {}): void => {
    window.parent.postMessage({ marker, channel, type, ...payload }, "*");
  };

  const documentText = (): string => document.body?.textContent ?? "";

  const rangeOffsets = (range: Range): { start: number; end: number } => {
    const before = document.createRange();
    before.selectNodeContents(document.body);
    before.setEnd(range.startContainer, range.startOffset);
    const through = document.createRange();
    through.selectNodeContents(document.body);
    through.setEnd(range.endContainer, range.endOffset);
    return { start: before.toString().length, end: through.toString().length };
  };

  const makeAnchor = (range: Range): TextCommentAnchor | null => {
    const text = documentText();
    const { start, end } = rangeOffsets(range);
    const quote = text.slice(start, end);
    if (!quote.trim() || quote.length > 10_000) return null;
    return {
      kind: "text",
      quote,
      prefix: text.slice(Math.max(0, start - 32), start),
      suffix: text.slice(end, end + 32),
      start,
      end,
    };
  };

  const textIndex = (): {
    text: string;
    entries: Array<{ node: Text; start: number; end: number }>;
  } => {
    const walker = document.createTreeWalker(
      document.body,
      NodeFilter.SHOW_TEXT,
    );
    const entries: Array<{ node: Text; start: number; end: number }> = [];
    let text = "";
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const textNode = node as Text;
      const start = text.length;
      text += textNode.data;
      entries.push({ node: textNode, start, end: text.length });
    }
    return { text, entries };
  };

  const rangeAt = (
    index: ReturnType<typeof textIndex>,
    start: number,
    end: number,
  ): Range | null => {
    const find = (offset: number) => {
      let low = 0;
      let high = index.entries.length - 1;
      let match: (typeof index.entries)[number] | null = null;
      while (low <= high) {
        const middle = (low + high) >> 1;
        const entry = index.entries[middle];
        if (offset < entry.start) high = middle - 1;
        else if (offset > entry.end) low = middle + 1;
        else {
          match = entry;
          high = middle - 1;
        }
      }
      return match;
    };

    const startEntry = find(start);
    const endEntry = find(end);
    if (!startEntry || !endEntry) return null;
    try {
      const range = document.createRange();
      range.setStart(startEntry.node, start - startEntry.start);
      range.setEnd(endEntry.node, end - endEntry.start);
      return range;
    } catch {
      return null;
    }
  };

  const installStyles = (): void => {
    const style = document.createElement("style");
    style.setAttribute("data-posthog-artifact-comments", "");
    style.textContent =
      "::highlight(posthog-artifact-comment){background:rgba(250,204,21,.32);color:inherit}::highlight(posthog-artifact-comment-active){background:rgba(250,204,21,.48);color:inherit}";
    (document.head ?? document.documentElement).appendChild(style);
  };

  const copyRect = (rect: BridgeRect): BridgeRect => ({
    top: rect.top,
    left: rect.left,
    right: rect.right,
    bottom: rect.bottom,
    width: rect.width,
    height: rect.height,
  });

  const hideAction = (): void => {
    if (state.button) state.button.style.display = "none";
    state.action = null;
  };

  const activateAction = (event: MouseEvent): void => {
    event.preventDefault();
    event.stopPropagation();
    const action = state.action;
    if (!action) {
      hideAction();
      return;
    }
    state.activeRange = action.range;
    send("selection", action.message);
    hideAction();
    window.getSelection()?.removeAllRanges();
  };

  const actionButton = (): HTMLButtonElement => {
    if (state.button?.isConnected) return state.button;

    const host = document.createElement("posthog-comment-action");
    host.setAttribute("data-selection-comment-overlay", "");
    host.style.cssText =
      "all:initial!important;display:block!important;position:fixed!important;top:0!important;left:0!important;width:0!important;height:0!important;overflow:visible!important;z-index:2147483647!important";
    const root = host.attachShadow({ mode: "open" });
    const style = document.createElement("style");
    style.textContent = buttonCss;
    root.appendChild(style);

    const button = document.createElement("button");
    button.type = "button";
    button.className = "ph-comment-action-button";
    button.setAttribute("aria-label", "Comment");
    button.innerHTML = `${actionIcon}<span>Comment</span>`;
    applyActionTheme(state.theme, themes, button);
    button.style.display = "none";
    button.addEventListener("click", activateAction);
    root.appendChild(button);
    document.documentElement.appendChild(host);
    state.button = button;
    return button;
  };

  const positionAction = (): void => {
    const selection = window.getSelection();
    if (!selection || selection.isCollapsed || selection.rangeCount === 0) {
      hideAction();
      return;
    }
    const value = selection.toString().trim();
    if (value.length < 2 || value.length > 10_000) {
      hideAction();
      return;
    }

    const range = selection.getRangeAt(0);
    const anchor = makeAnchor(range);
    if (!anchor) {
      hideAction();
      return;
    }
    const rect = anchorRect(
      range.getClientRects?.() ?? [],
      range.getBoundingClientRect(),
    );
    if (!rect || (rect.width === 0 && rect.height === 0)) {
      hideAction();
      return;
    }

    const button = actionButton();
    const buttonBox = button.getBoundingClientRect();
    const position = placeAction(
      { top: rect.top, right: rect.right, bottom: rect.bottom },
      { width: window.innerWidth, height: window.innerHeight },
      { width: buttonBox.width || 104, height: buttonBox.height || 28 },
    );
    button.style.left = `${position.left}px`;
    button.style.top = `${position.top}px`;
    button.style.display = "flex";

    const triggerRect = button.getBoundingClientRect();
    state.action = {
      range,
      message: {
        anchor,
        rect: copyRect(rect),
        // Electron validates this legacy field before forwarding the message.
        triggerRect: copyRect(triggerRect),
      },
    };
  };

  const updateComposerPosition = (): void => {
    const range = state.activeRange;
    if (!range) return;
    try {
      const rect = anchorRect(
        range.getClientRects?.() ?? [],
        range.getBoundingClientRect(),
      );
      if (rect && (rect.width > 0 || rect.height > 0)) {
        send("selection-position", { rect: copyRect(rect) });
      }
    } catch {
      state.activeRange = null;
    }
  };

  const scheduleComposerPosition = (): void => {
    if (state.positionFrame) return;
    if (!window.requestAnimationFrame) {
      updateComposerPosition();
      return;
    }
    state.positionFrame = window.requestAnimationFrame(() => {
      state.positionFrame = 0;
      updateComposerPosition();
    });
  };

  const selectionChanged = (): void => {
    clearTimeout(state.selectionTimer);
    state.selectionTimer = window.setTimeout(positionAction, 80);
  };

  const renderComments = (items: unknown): void => {
    state.items = Array.isArray(items) ? (items as BridgeComment[]) : [];
    state.entries = [];
    const normal = HighlightConstructor ? new HighlightConstructor() : null;
    const active = HighlightConstructor ? new HighlightConstructor() : null;
    const resolutions: Array<{ id: string; status: string }> = [];
    const index = textIndex();

    for (const item of state.items) {
      const resolved = resolveAnchor(index.text, item.anchor);
      if (!resolved) {
        resolutions.push({ id: item.id, status: "orphaned" });
        continue;
      }
      const range = rangeAt(index, resolved.start, resolved.end);
      if (!range) {
        resolutions.push({ id: item.id, status: "orphaned" });
        continue;
      }
      state.entries.push({ id: item.id, range });
      resolutions.push({ id: item.id, status: resolved.status });
      (item.active ? active : normal)?.add(range);
    }

    if (normal && active && highlightRegistry) {
      highlightRegistry.set("posthog-artifact-comment", normal);
      highlightRegistry.set("posthog-artifact-comment-active", active);
    }
    send("resolutions", { items: resolutions });
  };

  const locateComment = (id: string): void => {
    const entry = state.entries.find((candidate) => candidate.id === id);
    const node = entry?.range.startContainer;
    const target =
      node?.nodeType === Node.ELEMENT_NODE
        ? (node as Element)
        : node?.parentElement;
    target?.scrollIntoView({ behavior: "smooth", block: "center" });
  };

  installSettleGate(document, {
    onGestureStart: hideAction,
    onSelectionSettled: positionAction,
    onIdleSelectionChange: selectionChanged,
    onGestureCancel: hideAction,
  });
  document.addEventListener(
    "scroll",
    () => {
      hideAction();
      scheduleComposerPosition();
    },
    true,
  );
  document.addEventListener(
    "click",
    (event) => {
      const target = event.target;
      const link = target instanceof Element ? target.closest("a[href]") : null;
      if (link) {
        event.preventDefault();
        event.stopPropagation();
        send("open-external", { href: (link as HTMLAnchorElement).href });
        return;
      }

      for (const entry of state.entries) {
        for (const rect of entry.range.getClientRects()) {
          if (
            event.clientX >= rect.left &&
            event.clientX <= rect.right &&
            event.clientY >= rect.top &&
            event.clientY <= rect.bottom
          ) {
            event.preventDefault();
            event.stopPropagation();
            send("activate", { id: entry.id });
            return;
          }
        }
      }
    },
    true,
  );

  new MutationObserver(() => {
    if (state.items.length === 0 || state.renderTimer) return;
    state.renderTimer = window.setTimeout(() => {
      state.renderTimer = 0;
      renderComments(state.items);
    }, 500);
  }).observe(document.body, {
    childList: true,
    characterData: true,
    subtree: true,
  });

  window.addEventListener("message", (event) => {
    if (event.source !== window.parent) return;
    const data = event.data as Record<string, unknown> | null;
    if (!data || data.marker !== marker || data.channel !== channel) return;
    if (data.type === "comments") renderComments(data.items);
    else if (data.type === "selection-dismissed") {
      state.activeRange = null;
      if (state.positionFrame) window.cancelAnimationFrame(state.positionFrame);
      state.positionFrame = 0;
    } else if (
      data.type === "locate" &&
      typeof data.id === "string" &&
      typeof data.nonce === "number" &&
      data.nonce !== state.locateNonce
    ) {
      state.locateNonce = data.nonce;
      locateComment(data.id);
    } else if (
      data.type === "theme" &&
      (data.theme === "light" || data.theme === "dark")
    ) {
      state.theme = data.theme;
      if (state.button) applyActionTheme(data.theme, themes, state.button);
    }
  });

  installStyles();
  send("ready");
}

/**
 * Runs inside the isolated artifact document. It never receives credentials
 * or writes to the API; selection traffic uses a per-view host channel.
 */
function artifactHtmlCommentBridge(
  channel: string,
  theme: CommentSurfaceTheme,
  nonce?: string,
): string {
  const nonceAttribute = nonce ? ` nonce="${nonce}"` : "";
  return `<script${nonceAttribute} data-posthog-artifact-comments>
(${runArtifactHtmlCommentBridge.toString()})({
  channel: ${JSON.stringify(channel)},
  marker: ${JSON.stringify(BRIDGE_MARKER)},
  initialTheme: ${JSON.stringify(theme)},
  themes: ${JSON.stringify(COMMENT_ACTION_BUTTON_THEMES)},
  actionIcon: ${JSON.stringify(COMMENT_ACTION_ICON_SVG)},
  buttonCss: ${JSON.stringify(commentActionButtonCss())},
  setActionTheme: ${setCommentActionTheme.toString()},
  placeAction: ${computeCommentActionPlacement.toString()},
  anchorRect: ${commentActionAnchorRect.toString()},
  resolveAnchor: ${resolveTextCommentAnchor.toString()},
  installSelectionSettleGate: ${installSelectionSettleGate.toString()},
});
</script>`;
}

export function injectArtifactHtmlCommentBridge(
  html: string,
  options: {
    channel: string;
    theme: CommentSurfaceTheme;
    nonce?: string;
  },
): string {
  const bridge = artifactHtmlCommentBridge(
    options.channel,
    options.theme,
    options.nonce,
  );
  const bodyEnd = html.toLowerCase().lastIndexOf("</body>");
  if (bodyEnd >= 0) {
    return `${html.slice(0, bodyEnd)}${bridge}${html.slice(bodyEnd)}`;
  }
  const htmlEnd = html.toLowerCase().lastIndexOf("</html>");
  if (htmlEnd >= 0) {
    return `${html.slice(0, htmlEnd)}${bridge}${html.slice(htmlEnd)}`;
  }
  return `${html}${bridge}`;
}
