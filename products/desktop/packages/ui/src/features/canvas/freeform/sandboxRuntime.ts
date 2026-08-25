import {
  buildImportMap,
  FREEFORM_BABEL_URL,
  FREEFORM_ESM_HOST,
  FREEFORM_POSTHOG_JS_URL,
  FREEFORM_QUILL_CSS_URLS,
} from "@posthog/core/canvas/freeformWhitelist";
import { resolveTextCommentAnchor } from "@posthog/core/comments/anchors";
import {
  commentActionAnchorRect,
  installSelectionSettleGate,
} from "@posthog/ui/features/sessions/components/selectionCommentAction";

// Builds the HTML document loaded into the freeform-canvas sandbox iframe.
//
// Security notes (see docs/CANVAS-FREEFORM-REACT-PLAN.md):
//   - The iframe is mounted with sandbox="allow-scripts" and NO
//     allow-same-origin, so this document runs at a null origin: it cannot read
//     the host's cookies/storage or touch the host DOM. That is also why all
//     data access is postMessage, not a shared client object.
//   - The user's canvas code is NEVER interpolated into this HTML. It arrives
//     later as a postMessage `init` frame and is run from a Blob module URL, so
//     there is no string-injection path through the document itself.
//   - The CSP is the third isolation layer. It allows the esm.sh CDN, because
//     this document transpiles and resolves imports in the browser.
//
// This is the AUTHORING surface only: it renders a canvas whose build hasn't
// succeeded yet, and card previews. A published canvas is a compiled artifact
// rendered by BuiltCanvas, which self-hosts its assets behind its own CSP and
// gates `ph.*` on the build's capability manifest.

// Which in-browser Tailwind engine the sandbox runs. "v4" matches the
// Quill version we ship (Quill is authored for Tailwind v4) and lets us drop the
// v3 Play CDN's preflight-off hack, the `not-disabled` variant shim, the manual
// `@layer base` reset, and the hand-mirrored color map — v4's layered preflight
// and `@theme inline` token mapping cover all of it. "v3" keeps the legacy Play
// CDN path as a one-line fallback while v4 is validated against real canvases.
const TAILWIND_ENGINE: "v3" | "v4" = "v4";

// Tailwind v4 browser JIT. `@import "tailwindcss"` brings in v4's layered theme/
// base(preflight)/components/utilities — so preflight sits in `@layer base`,
// BELOW Quill's `@layer components` (primitives.css), and can't clobber Quill
// the way v3's unlayered preflight did. `@theme inline` maps Quill's CSS-variable
// tokens to v4 color keys so `bg-card`, `text-muted-foreground`, `bg-fill-hover`
// etc. generate, referencing the vars tokens.css defines on :root/.dark. Only
// DEFINED tokens are mapped (no secondary/accent/popover — those have no vars).
// The version is PINNED (frozen, like freeformWhitelist) so every canvas renders
// against a known Tailwind build and can't drift onto a new release silently.
const TAILWIND_V4 = `<script type="module" src="https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4.3.1"></script>
<style type="text/tailwindcss">
@import "tailwindcss";
/* Drive \`dark:\` off the \`.dark\` class the host toggles (not prefers-color-scheme),
   so the canvas follows the user's PostHog theme even when it differs from the OS. */
@custom-variant dark (&:where(.dark, .dark *));
@theme inline {
  --color-border: var(--border);
  --color-input: var(--input);
  --color-ring: var(--ring);
  --color-chrome: var(--chrome);
  --color-background: var(--background);
  --color-foreground: var(--foreground);
  --color-primary: var(--primary);
  --color-primary-foreground: var(--primary-foreground);
  --color-destructive: var(--destructive);
  --color-destructive-foreground: var(--destructive-foreground);
  --color-muted: var(--muted);
  --color-muted-foreground: var(--muted-foreground);
  --color-card: var(--card);
  --color-card-foreground: var(--card-foreground);
  --color-success: var(--success);
  --color-success-foreground: var(--success-foreground);
  --color-warning: var(--warning);
  --color-warning-foreground: var(--warning-foreground);
  --color-info: var(--info);
  --color-info-foreground: var(--info-foreground);
  --color-fill-hover: var(--fill-hover);
  --color-fill-selected: var(--fill-selected);
  --color-fill-expanded: var(--fill-expanded);
  --radius-lg: var(--radius);
  --radius-md: calc(var(--radius) - 2px);
  --radius-sm: calc(var(--radius) - 4px);
}
</style>`;

// A LAYERED element reset for the LEGACY v3 path only. v3's Play CDN preflight is
// unlayered (it clobbers Quill's `@layer components`), so we run it with preflight
// off and ship this minimal reset in `@layer base` — pinned below `components` so
// Quill keeps winning and bare HTML elements still get tamed. v4 doesn't need it
// (its own preflight is correctly layered).
const LEGACY_RESET = `<style>
@layer base, components, utilities;
@layer base {
  h1, h2, h3, h4, h5, h6, p, figure, blockquote, dl, dd { margin: 0; }
  h1, h2, h3, h4, h5, h6 { font-size: inherit; font-weight: inherit; }
  ul, ol { margin: 0; padding: 0; list-style: none; }
  a { color: inherit; text-decoration: inherit; }
  img, svg, video, canvas { display: block; max-width: 100%; }
  button, input, select, textarea { font: inherit; color: inherit; }
  button { padding: 0; background: none; border: 0; cursor: pointer; }
  table { border-collapse: collapse; }
}
</style>`;

// Legacy Tailwind v3 Play CDN path (preflight off + hand-mirrored token map).
// Retained as a fallback behind TAILWIND_ENGINE while v4 is validated.
const TAILWIND_V3 = `<script src="https://cdn.tailwindcss.com"></script>
<script>
  tailwind.config = {
  corePlugins: { preflight: false },
  darkMode: "class",
  plugins: [
    tailwind.plugin(({ addVariant }) => {
      addVariant("not-disabled", "&:not(:disabled)");
    }),
  ],
  theme: { extend: {
    colors: {
      border: "var(--border)", input: "var(--input)", ring: "var(--ring)",
      background: "var(--background)", foreground: "var(--foreground)",
      chrome: "var(--chrome)",
      primary: { DEFAULT: "var(--primary)", foreground: "var(--primary-foreground)" },
      destructive: { DEFAULT: "var(--destructive)", foreground: "var(--destructive-foreground)" },
      muted: { DEFAULT: "var(--muted)", foreground: "var(--muted-foreground)" },
      card: { DEFAULT: "var(--card)", foreground: "var(--card-foreground)" },
      success: { DEFAULT: "var(--success)", foreground: "var(--success-foreground)" },
      warning: { DEFAULT: "var(--warning)", foreground: "var(--warning-foreground)" },
      info: { DEFAULT: "var(--info)", foreground: "var(--info-foreground)" },
      fill: {
        hover: "var(--fill-hover)",
        selected: "var(--fill-selected)",
        expanded: "var(--fill-expanded)",
      },
    },
    borderRadius: { lg: "var(--radius)", md: "calc(var(--radius) - 2px)", sm: "calc(var(--radius) - 4px)" },
  } } };
</script>`;

// Decodes literal \uXXXX / \u{...} escape sequences in a string. Exported for
// tests; its source is interpolated into the sandbox bootstrap below so the
// iframe runs this exact implementation.
export function decodeJsxUnicodeEscapes(value: string): string {
  return value.replace(
    /\\u\{([0-9a-fA-F]{1,6})\}|\\u([0-9a-fA-F]{4})/g,
    (match, braced, plain) => {
      try {
        return String.fromCodePoint(Number.parseInt(braced || plain, 16));
      } catch {
        return match;
      }
    },
  );
}

// Resolves a click target to the absolute URL of an enclosing target="_blank"
// anchor, or null. Interpolated into the sandbox bootstrap; exported for tests.
export function resolveExternalAnchorUrl(target: unknown): string | null {
  const anchor = target instanceof Element ? target.closest("a[href]") : null;
  if (!anchor) return null;
  // HTML matches the _blank keyword ASCII-case-insensitively.
  if ((anchor.getAttribute("target") ?? "").toLowerCase() !== "_blank") {
    return null;
  }
  // getAttribute, not the .href property: SVG anchors expose SVGAnimatedString
  // there, and relative hrefs would resolve against the host's base URL.
  const href = anchor.getAttribute("href") ?? "";
  try {
    return new URL(href).href;
  } catch {
    return null;
  }
}

export function isInteractiveCanvasCommentTarget(target: unknown): boolean {
  return (
    target instanceof Element &&
    !!target.closest(
      "a,button,input,select,textarea,[role=button],[contenteditable=true],[onclick]",
    )
  );
}

export function buildSandboxDocument(
  // The PostHog host, when in-iframe analytics/replay is enabled. Opens CSP for
  // posthog-js to load its recorder and POST events/replay to ingest.
  analyticsApiHost?: string,
): string {
  const importMap = JSON.stringify(buildImportMap());
  const csp = contentSecurityPolicy(analyticsApiHost);

  // Quill components emit Tailwind utility classes (layout — `inline-flex`,
  // `items-center` — AND token colors like `bg-card`, `text-muted-foreground`)
  // ALONGSIDE their `.quill-*` BEM classes. The linked Quill stylesheets style
  // the BEM half; the utilities are dead without Tailwind, so the sandbox runs a
  // JIT-in-browser Tailwind. Quill is authored for Tailwind v4, so we run the v4
  // browser engine: its preflight is properly `@layer base` (sorts BELOW Quill's
  // `@layer components`, so it can't clobber them — no preflight-off hack, no
  // hand-rolled reset), it has native `not-*` variants (no `not-disabled` shim),
  // and `@theme inline` maps Quill's tokens straight to v4 color keys. The whole
  // hand-mirrored color map + reset the v3 Play CDN forced us into collapses to
  // the token block below.
  const tailwind = TAILWIND_ENGINE === "v4" ? TAILWIND_V4 : TAILWIND_V3;
  // v4 preflight is the layered reset; only the legacy v3 path needs the manual
  // `@layer base` reset (v3's Play CDN preflight is unlayered, so it's off).
  const reset = TAILWIND_ENGINE === "v3" ? LEGACY_RESET : "";

  // The bootstrap module. It is static (no user input) so it can be inlined
  // safely. It waits for `init`, transpiles the canvas with Babel, runs it from
  // a Blob module (which resolves bare imports via the import map above), and
  // reports lifecycle + errors back to the host.
  const bootstrap = /* js */ `
    import * as Babel from "${FREEFORM_BABEL_URL}";
    const CHANNEL = "posthog-canvas";
    const post = (msg) => parent.postMessage({ channel: CHANNEL, ...msg }, "*");

    // --- data shim: the ONLY way canvas code reaches PostHog. No token here. ---
    const pending = new Map();
    let reqSeq = 0;
    const call = (method, payload) =>
      new Promise((resolve, reject) => {
        const id = String(++reqSeq);
        pending.set(id, { resolve, reject });
        post({ type: "data-request", id, method, payload });
      });
    // posthog-js runs IN here (the only way replay records the app's DOM). It is
    // booted by init when analytics config is present; until then capture falls
    // back to the host-mediated path.
    let phClient = null;
    window.ph = {
      // Run a named, server-stored query — the published tier's model. The host
      // still rejects it (Phase 3).
      run: (name, params) => call("run", { name, params: params ?? {} }),
      // PREFERRED data path: load a SAVED, validated insight by its short id and
      // render its STORED result from the insights endpoint (not a fresh /query/
      // run). Pass the date picker's window to re-scope it:
      // \`ph.loadInsight("AbC123", { dateRange: { date_from, date_to } })\`.
      // A SQL insight's \`{variables.x}\` placeholders are set per call, keyed by
      // code name: \`ph.loadInsight("AbC123", { variables: { product: "surveys" } })\`
      // — so one saved insight serves a whole board. The host REJECTS a variable the
      // insight doesn't use, rather than quietly falling back to its saved value.
      // Returns \`{ columns, results }\` — SAME shape as ph.query: a trends-style
      // insight returns SERIES OBJECTS, a SQL insight returns ROWS.
      loadInsight: (shortId, opts) =>
        call("loadInsight", {
          shortId,
          dateRange: opts && opts.dateRange,
          variables: opts && opts.variables,
          refresh: opts && opts.refresh,
        }),
      // Run a query. Pass a TYPED query node (\`{ kind: "TrendsQuery", … }\`) for
      // UI-matching numbers (preferred), or an inline HogQL string (escape hatch).
      // A built canvas needs \`capabilities.posthog.inlineQueries\` for this.
      query: (queryOrHogql, params, opts) =>
        call(
          "query",
          typeof queryOrHogql === "string"
            ? { hogql: queryOrHogql, params: params ?? {}, refresh: opts && opts.refresh }
            : { query: queryOrHogql, params: params ?? {}, refresh: opts && opts.refresh },
        ),
      // Send an analytics event. Prefer in-iframe posthog-js (so it shares the
      // session/replay); otherwise host-mediated (no replay, still captured).
      capture: (event, properties, distinctId) => {
        if (phClient) {
          phClient.capture(event, properties ?? {});
          return Promise.resolve({ ok: true });
        }
        return call("capture", { event, properties: properties ?? {}, distinctId });
      },
      // Durable key-value memory, declared in capabilities.posthog.state.
      // Scope "user" (default) is private to this viewer; "shared" is one
      // value per canvas, visible to the whole team. Values are JSON, capped
      // at 64 KB serialized and 256 keys per scope; setting null deletes:
      // \`ph.state.set("board", { columns: 3 }, { scope: "shared" })\`.
      state: {
        get: (key, opts) => call("stateGet", { key, scope: (opts && opts.scope) || "user" }),
        set: (key, value, opts) =>
          call("stateSet", { key, value: value === undefined ? null : value, scope: (opts && opts.scope) || "user" }),
        list: (opts) => call("stateList", { scope: opts && opts.scope }),
      },
      // Write into PostHog as the viewer. Every verb must be declared in
      // capabilities.posthog.actions; wire invocations to explicit user
      // gestures (a button), never to load or render:
      // \`ph.actions.invoke("tasks.create", { title, description })\`.
      actions: {
        invoke: (verb, payload) => call("actionInvoke", { verb, payload: payload ?? {} }),
      },
      // Ask the authoring agent for a change; the host shows the exact prompt
      // and asks the viewer to approve before anything is dispatched:
      // \`ph.agent.request("Make the square blue")\`.
      agent: {
        request: (prompt) => call("agentRequest", { prompt }),
      },
      // Brokered by the host: PostHog-only https URLs, rate-limited, and
      // ignored while the canvas is unfocused (no auto-opens on load).
      openExternal: (url) => post({ type: "open-external", url }),
      // Navigate the host app. Fire-and-forget: the host validates the intent
      // against its allowlist and routes within the current channel. The canvas
      // cannot pick the channel or an arbitrary path — only these four targets.
      navigate: {
        toTask: (taskId) => post({ type: "navigate", nav: { target: "task", taskId } }),
        toNewTask: () => post({ type: "navigate", nav: { target: "new-task" } }),
        toCanvas: (dashboardId) => post({ type: "navigate", nav: { target: "canvas", dashboardId } }),
        toNewCanvas: () => post({ type: "navigate", nav: { target: "new-canvas" } }),
      },
    };

    // Keep target="_blank" anchors working without popup permission. Capture
    // phase so stopPropagation() can't swallow the click; the open is deferred
    // a tick so preventDefault() is honored (the native popup attempt is
    // sandbox-blocked regardless, so we never call preventDefault ourselves).
    const resolveExternalAnchorUrl = ${resolveExternalAnchorUrl.toString()};
    document.addEventListener(
      "click",
      (event) => {
        const url = resolveExternalAnchorUrl(event.target);
        if (!url) return;
        setTimeout(() => {
          if (!event.defaultPrevented) window.ph.openExternal(url);
        }, 0);
      },
      true,
    );

    const selectionAnchorRect = ${commentActionAnchorRect.toString()};
    let textSelectionPublished = false;
    const clearTextSelection = () => {
      if (!textSelectionPublished) return;
      textSelectionPublished = false;
      post({ type: "text-selection-cleared" });
    };
    let selectionTimer = 0;
    const reportTextSelection = () => {
      clearTimeout(selectionTimer);
      selectionTimer = setTimeout(() => {
      const selection = window.getSelection();
      if (!selection || selection.isCollapsed || selection.rangeCount === 0) {
        clearTextSelection();
        return;
      }
      const range = selection.getRangeAt(0);
      if (!document.body.contains(range.startContainer) || !document.body.contains(range.endContainer)) {
        clearTextSelection();
        return;
      }
      const before = document.createRange();
      before.selectNodeContents(document.body);
      before.setEnd(range.startContainer, range.startOffset);
      const through = document.createRange();
      through.selectNodeContents(document.body);
      through.setEnd(range.endContainer, range.endOffset);
      const text = commentTextIndex().text;
      const start = before.toString().length;
      const end = through.toString().length;
      const quote = text.slice(start, end);
      if (!quote.trim() || quote.length > 10000) {
        clearTextSelection();
        return;
      }
      // The END line's rect, so the host anchors the comment action where the
      // pointer was released rather than at the whole-range bounding box.
      const rect = selectionAnchorRect(range.getClientRects(), range.getBoundingClientRect());
      textSelectionPublished = true;
      post({
        type: "text-selection",
        selection: {
          quote,
          prefix: text.slice(Math.max(0, start - 32), start),
          suffix: text.slice(end, end + 32),
          start,
          end,
          rect: { top: rect.top, right: rect.right, bottom: rect.bottom, left: rect.left },
        },
      });
      }, 80);
    };
    // Report the selection only once it settles, so the host's comment action
    // doesn't chase the cursor mid-drag. The settle callback re-reads the live
    // selection, which self-corrects clicks that didn't change the selection.
    const selectionSettleGate = ${installSelectionSettleGate.toString()};
    // Dropping the pending report matters: a new drag started within the
    // debounce window would otherwise publish the previous selection mid-drag.
    const abortTextSelection = () => {
      clearTimeout(selectionTimer);
      clearTextSelection();
    };
    selectionSettleGate(document, {
      onGestureStart: abortTextSelection,
      onSelectionSettled: reportTextSelection,
      onIdleSelectionChange: reportTextSelection,
      onGestureCancel: abortTextSelection,
    });
    document.addEventListener("scroll", abortTextSelection, true);
    const clearNativeTextSelection = () => {
      window.getSelection()?.removeAllRanges();
      clearTextSelection();
    };

    const commentHighlightStyle = document.createElement("style");
    commentHighlightStyle.textContent = "::highlight(posthog-canvas-comment){background:rgba(250,204,21,.32);color:inherit}::highlight(posthog-canvas-comment-active){background:rgba(250,204,21,.48);color:inherit}";
    document.head.appendChild(commentHighlightStyle);
    let currentCommentHighlights = [];
    let commentRanges = [];
    let cachedCommentTextIndex = null;
    const commentTextIndex = () => {
      if (cachedCommentTextIndex) return cachedCommentTextIndex;
      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      const entries = [];
      let text = "";
      for (let node = walker.nextNode(); node; node = walker.nextNode()) {
        const start = text.length;
        text += node.data;
        entries.push({ node, start, end: text.length });
      }
      cachedCommentTextIndex = { text, entries };
      return cachedCommentTextIndex;
    };
    const commentRangeAt = (index, start, end) => {
      const find = (offset) => {
        let low = 0, high = index.entries.length - 1, match = null;
        while (low <= high) {
          const middle = (low + high) >> 1;
          const entry = index.entries[middle];
          if (offset < entry.start) high = middle - 1;
          else if (offset > entry.end) low = middle + 1;
          else { match = entry; high = middle - 1; }
        }
        return match;
      };
      const startEntry = find(start), endEntry = find(end);
      if (!startEntry || !endEntry) return null;
      const range = document.createRange();
      range.setStart(startEntry.node, start - startEntry.start);
      range.setEnd(endEntry.node, end - endEntry.start);
      return range;
    };
    const resolveCommentAnchor = ${resolveTextCommentAnchor.toString()};
    const renderCommentHighlights = (items) => {
      currentCommentHighlights = items || [];
      commentRanges = [];
      if (!window.Highlight || !window.CSS || !CSS.highlights) return;
      const normal = new Highlight();
      const active = new Highlight();
      const index = commentTextIndex();
      for (const item of currentCommentHighlights) {
        const resolved = resolveCommentAnchor(index.text, item.anchor);
        const range = resolved && commentRangeAt(index, resolved.start, resolved.end);
        if (range) {
          commentRanges.push({ id: item.id, range });
          (item.active ? active : normal).add(range);
        }
      }
      CSS.highlights.set("posthog-canvas-comment", normal);
      CSS.highlights.set("posthog-canvas-comment-active", active);
    };
    let commentHighlightTimer = 0;
    new MutationObserver(() => {
      cachedCommentTextIndex = null;
      if (!currentCommentHighlights.length || commentHighlightTimer) return;
      commentHighlightTimer = setTimeout(() => {
        commentHighlightTimer = 0;
        renderCommentHighlights(currentCommentHighlights);
      }, 2000);
    }).observe(document.body, { childList: true, characterData: true, subtree: true });
    const isInteractiveCommentTarget = ${isInteractiveCanvasCommentTarget.toString()};
    document.addEventListener("click", (event) => {
      const selection = window.getSelection();
      if ((selection && !selection.isCollapsed) || isInteractiveCommentTarget(event.target)) return;
      for (const item of commentRanges) {
        for (const rect of item.range.getClientRects()) {
          if (event.clientX >= rect.left && event.clientX <= rect.right && event.clientY >= rect.top && event.clientY <= rect.bottom) {
            event.preventDefault();
            event.stopPropagation();
            post({ type: "comment-activate", id: item.id });
            return;
          }
        }
      }
    }, true);

    // Boot posthog-js with the PUBLIC key the host passed in (never the read
    // token). Enables session replay so the author/viewer can be watched.
    const bootAnalytics = async (cfg) => {
      if (phClient || !cfg) return;
      try {
        const mod = await import("${FREEFORM_POSTHOG_JS_URL}");
        const posthog = mod.default || mod.posthog || mod;
        posthog.init(cfg.publicKey, {
          api_host: cfg.apiHost,
          // No storage on a null-origin sandbox → memory session; the
          // usercontent origin (shared tier) persists per-viewer.
          persistence: cfg.persist ? "localStorage+cookie" : "memory",
          capture_pageview: false,
          disable_session_recording: false,
          loaded: (ph) => {
            if (cfg.distinctId) ph.identify(cfg.distinctId);
          },
        });
        phClient = posthog;
        window.posthog = posthog;
      } catch (err) {
        reportError(
          "analytics init failed: " + (err && err.message),
          err && err.stack,
        );
      }
    };

    // --- theme: mirror the host's light/dark by toggling \`.dark\` on the root,
    // exactly as the main app does. Quill's CSS tokens (:root / .dark) and the
    // \`dark:\` Tailwind utilities both key off this class, so the whole canvas
    // flips. Applied on init and on every live \`set-theme\` frame.
    const applyTheme = (theme) =>
      document.documentElement.classList.toggle("dark", theme === "dark");

    window.addEventListener("keydown", (e) => {
      if (!e.isTrusted || (!e.metaKey && !e.ctrlKey)) return;
      post({
        type: "keydown",
        key: e.key,
        code: e.code,
        metaKey: e.metaKey,
        ctrlKey: e.ctrlKey,
        shiftKey: e.shiftKey,
        altKey: e.altKey,
      });
    });

    // --- error reporting (feeds the host's self-repair loop) ---
    const reportError = (message, stack) =>
      post({ type: "error", message: String(message ?? "Unknown error"), stack });
    window.addEventListener("error", (e) =>
      reportError(e.message, e.error && e.error.stack),
    );
    window.addEventListener("unhandledrejection", (e) =>
      reportError(
        (e.reason && e.reason.message) || e.reason,
        e.reason && e.reason.stack,
      ),
    );

    // JSX text and attribute strings never process \\uXXXX escapes (they render
    // verbatim, e.g. "\\u00b7" instead of "·"), but generated canvases still
    // contain them despite the prompt rules — decode at transpile time so both
    // new and already-saved canvases render the real characters. Escapes inside
    // JS string/template literals are untouched (Babel already decoded those).
    const decodeUnicodeEscapes = ${decodeJsxUnicodeEscapes.toString()};
    const jsxUnicodeEscapesPlugin = () => ({
      visitor: {
        JSXText(path) {
          const decoded = decodeUnicodeEscapes(path.node.value);
          if (decoded !== path.node.value) {
            path.node.value = decoded;
          }
        },
        JSXAttribute(path) {
          const v = path.node.value;
          if (v && v.type === "StringLiteral") {
            const decoded = decodeUnicodeEscapes(v.value);
            if (decoded !== v.value) {
              v.value = decoded;
              v.extra = undefined; // drop stale raw so the decoded value is emitted
            }
          }
        },
      },
    });

    let root = null;
    // mount() is async and is called once per streamed code snapshot, so several
    // runs overlap on their awaits. Without ordering, a slower EARLIER (partial,
    // often invalid) snapshot could run root.render last and clobber the latest
    // good render — the bug where live edits don't appear until you revisit.
    // A monotonic sequence makes only the newest mount commit its render/error;
    // superseded runs bail out after each await.
    let mountSeq = 0;
    const mount = async (code) => {
      const seq = ++mountSeq;
      try {
        const out = Babel.transform(code, {
          filename: "canvas.tsx",
          plugins: [jsxUnicodeEscapesPlugin],
          presets: [
            ["react", { runtime: "automatic" }],
            ["typescript", { isTSX: true, allExtensions: true, onlyRemoveTypeImports: true }],
          ],
        }).code;
        const url = URL.createObjectURL(
          new Blob([out], { type: "text/javascript" }),
        );
        let mod;
        try {
          mod = await import(url);
        } finally {
          URL.revokeObjectURL(url);
        }
        if (seq !== mountSeq) return; // a newer snapshot superseded this one
        const Comp = mod.default;
        if (typeof Comp !== "function") {
          throw new Error("Canvas must \`export default\` a React component.");
        }
        const React = await import("react");
        const { createRoot } = await import("react-dom/client");
        if (seq !== mountSeq) return;
        const el = document.getElementById("root");
        if (!root) root = createRoot(el);

        // Catch render-time throws so one bad render doesn't white-screen the
        // host; the error is reported and the host keeps showing last-good.
        class Boundary extends React.Component {
          constructor(p) { super(p); this.state = { error: null }; }
          static getDerivedStateFromError(error) { return { error }; }
          componentDidCatch(error) { reportError(error.message, error.stack); }
          render() {
            if (this.state.error) return null;
            return this.props.children;
          }
        }
        root.render(
          React.createElement(Boundary, null, React.createElement(Comp)),
        );
        // Let layout settle, then report success.
        requestAnimationFrame(() => {
          if (seq !== mountSeq) return;
          renderCommentHighlights(currentCommentHighlights);
          post({ type: "rendered" });
        });
      } catch (err) {
        // Only the latest snapshot reports — a superseded partial's parse error
        // must not surface as the canvas's error or flicker the host banner.
        if (seq !== mountSeq) return;
        let message = err && err.message;
        // Chrome reports a failed CDN fetch of the code's imports as an opaque
        // error naming the blob module; name the real dependency instead.
        if (message && message.indexOf("Failed to fetch dynamically imported module") !== -1) {
          message = "Couldn't load the canvas libraries from esm.sh. " +
            "Previewing an unbuilt canvas needs network access to https://esm.sh; " +
            "published canvases are unaffected.";
        }
        reportError(message, err && err.stack);
      }
    };

    window.addEventListener("message", (e) => {
      const d = e.data;
      if (!d || d.channel !== CHANNEL) return;
      if (d.type === "init") {
        applyTheme(d.theme);
        currentCommentHighlights = d.highlights || [];
        if (d.analytics) void bootAnalytics(d.analytics);
        void mount(d.code);
      } else if (d.type === "set-theme") {
        // Re-theme in place — no mount(), so the app keeps all its state.
        applyTheme(d.theme);
      } else if (d.type === "set-comment-highlights") {
        renderCommentHighlights(d.highlights);
      } else if (d.type === "clear-text-selection") {
        clearNativeTextSelection();
      } else if (d.type === "data-response") {
        const p = pending.get(d.id);
        if (!p) return;
        pending.delete(d.id);
        d.ok ? p.resolve(d.result) : p.reject(new Error(d.error || "data error"));
      }
    });

    post({ type: "ready" });
  `;

  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta http-equiv="Content-Security-Policy" content="${csp}" />
<script type="importmap">${importMap}</script>
${tailwind}
${reset}
${FREEFORM_QUILL_CSS_URLS.map(
  (href) => `<link rel="stylesheet" href="${href}" />`,
).join("\n")}
<style>
  *, *::before, *::after { box-sizing: border-box; }
  /* Fill the iframe viewport exactly so overflow scrolls on the iframe's own root
     scroller — the iframe is pinned to its parent's height and never grows it. */
  html, body { margin: 0; padding: 0; height: 100%; }
  /* No light default: leaving \`color-scheme\` alone lets the base canvas inherit
     the embedder's scheme (the host sets it on the iframe), so the first paint
     is already dark in a dark app. Once the host's theme message toggles
     \`.dark\`, this pins it so form controls and scrollbars match too. */
  html.dark { color-scheme: dark; }
  /* Track the theme via Quill's tokens (set on :root / .dark) so the page chrome
     flips with the host theme. Until those tokens land — the stylesheets are
     still loading, and \`.dark\` is only applied once the host's init/set-theme
     message arrives — stay transparent and inherit, so the host iframe's own
     themed background shows through. A hard light fallback here flashed white
     over a dark app every time a preview scrolled into view. */
  body { font-family: ui-sans-serif, system-ui, -apple-system, sans-serif; color: var(--foreground, inherit); background: var(--background, transparent); }
  #root { min-height: 100vh; }
</style>
</head>
<body>
<div id="root"></div>
<script type="module">${bootstrap}</script>
</body>
</html>`;
}

// The iframe CSP (third isolation layer). This document only ever renders a
// canvas its own author is editing, so it trusts the CDNs it has to fetch from
// to transpile and resolve imports. A published canvas is not served from here —
// it is a compiled artifact in BuiltCanvas, whose host document carries its own,
// far tighter policy. Do not widen this one on a published canvas's behalf.
function contentSecurityPolicy(analyticsApiHost?: string): string {
  const esm = FREEFORM_ESM_HOST;
  // posthog-js posts events to the api host and loads the recorder from the
  // region assets host; allow both. Wildcards cover PostHog Cloud regions; the
  // explicit api host covers self-hosted.
  const ph = analyticsApiHost
    ? `${analyticsApiHost} https://*.posthog.com https://*.i.posthog.com`
    : "";
  // Only the ACTIVE Tailwind engine's CDN is trusted (not both), and the v4
  // build is path-scoped to the @tailwindcss namespace on jsdelivr rather than
  // the whole origin — both narrow the code-execution sandbox's egress to
  // exactly what it fetches. v3's Play CDN loads from arbitrary sub-paths, so
  // it stays origin-scoped (it's only the fallback, off by default).
  const twCdn =
    TAILWIND_ENGINE === "v4"
      ? "https://cdn.jsdelivr.net/npm/@tailwindcss/"
      : "https://cdn.tailwindcss.com";
  return [
    "default-src 'none'",
    // Inline bootstrap + esm.sh modules + the transpiled Blob module + the
    // posthog-js recorder script + the in-browser Tailwind engine (JIT-compiles,
    // so 'unsafe-eval' is required).
    `script-src 'unsafe-inline' 'unsafe-eval' blob: ${twCdn} ${esm} ${ph}`,
    `style-src 'unsafe-inline' ${esm}`,
    `font-src data: ${esm}`,
    "img-src data: blob: https:",
    `worker-src blob:`,
    // esm.sh + Tailwind CDN sub-fetches; canvas DATA goes over postMessage (not
    // connect), but posthog-js events/replay DO use connect to the PostHog hosts.
    `connect-src ${esm} ${twCdn} ${ph}`,
  ].join("; ");
}
