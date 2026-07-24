import {
  buildImportMap,
  FREEFORM_BABEL_URL,
  FREEFORM_ESM_HOST,
  FREEFORM_POSTHOG_JS_URL,
  FREEFORM_QUILL_CSS_URLS,
} from "@posthog/core/canvas/freeformWhitelist";

// Builds the HTML document loaded into the freeform-canvas sandbox iframe.
//
// Security notes (see docs/canvas-freeform-react-plan.md):
//   - The iframe is mounted with sandbox="allow-scripts" and NO
//     allow-same-origin, so this document runs at a null origin: it cannot read
//     the host's cookies/storage or touch the host DOM. That is also why all
//     data access is postMessage, not a shared client object.
//   - The user's canvas code is NEVER interpolated into this HTML. It arrives
//     later as a postMessage `init` frame and is run from a Blob module URL, so
//     there is no string-injection path through the document itself.
//   - The CSP is the third isolation layer. Edit mode allows the esm.sh CDN (for
//     Babel + whitelisted packages). View/published mode (Phase 2) self-hosts
//     and forbids third-party egress entirely.
export type SandboxMode = "edit" | "view";

// Which in-browser Tailwind engine the EDIT-mode sandbox runs. "v4" matches the
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

export function buildSandboxDocument(
  mode: SandboxMode,
  // The PostHog host, when in-iframe analytics/replay is enabled. Opens CSP for
  // posthog-js to load its recorder and POST events/replay to ingest.
  analyticsApiHost?: string,
): string {
  const importMap = JSON.stringify(buildImportMap());
  const csp = contentSecurityPolicy(mode, analyticsApiHost);

  // Quill components emit Tailwind utility classes (layout — `inline-flex`,
  // `items-center` — AND token colors like `bg-card`, `text-muted-foreground`)
  // ALONGSIDE their `.quill-*` BEM classes. The linked Quill stylesheets style
  // the BEM half; the utilities are dead without Tailwind, so the sandbox runs a
  // JIT-in-browser Tailwind in EDIT mode (View/published mode forbids the CDN —
  // that tier self-hosts a compiled stylesheet, Phase 2). Quill is authored for
  // Tailwind v4, so we run the v4 browser engine: its preflight is properly
  // `@layer base` (sorts BELOW Quill's `@layer components`, so it can't clobber
  // them — no preflight-off hack, no hand-rolled reset), it has native `not-*`
  // variants (no `not-disabled` shim), and `@theme inline` maps Quill's tokens
  // straight to v4 color keys. The whole hand-mirrored color map + reset the v3
  // Play CDN forced us into collapses to the token block below.
  const tailwind =
    mode === "edit"
      ? TAILWIND_ENGINE === "v4"
        ? TAILWIND_V4
        : TAILWIND_V3
      : "";
  // v4 preflight is the layered reset; only the legacy v3 path needs the manual
  // `@layer base` reset (v3's Play CDN preflight is unlayered, so it's off).
  const reset = mode === "edit" && TAILWIND_ENGINE === "v3" ? LEGACY_RESET : "";

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
      // Run a named, server-stored query (the only shape allowed in view mode).
      run: (name, params) => call("run", { name, params: params ?? {} }),
      // PREFERRED data path: load a SAVED, validated insight by its short id and
      // render its STORED result from the insights endpoint (not a fresh /query/
      // run). Pass the date picker's window to re-scope it:
      // \`ph.loadInsight("AbC123", { dateRange: { date_from, date_to } })\`.
      // Returns \`{ columns, results }\` — SAME shape as ph.query: a trends-style
      // insight returns SERIES OBJECTS, a SQL insight returns ROWS.
      loadInsight: (shortId, opts) =>
        call("loadInsight", { shortId, dateRange: opts && opts.dateRange }),
      // Run a query. Pass a TYPED query node (\`{ kind: "TrendsQuery", … }\`) for
      // UI-matching numbers (preferred), or an inline HogQL string (escape hatch).
      // Edit mode only; rejected by the host in view mode.
      query: (queryOrHogql, params) =>
        call(
          "query",
          typeof queryOrHogql === "string"
            ? { hogql: queryOrHogql, params: params ?? {} }
            : { query: queryOrHogql, params: params ?? {} },
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
          post({ type: "rendered" });
        });
      } catch (err) {
        // Only the latest snapshot reports — a superseded partial's parse error
        // must not surface as the canvas's error or flicker the host banner.
        if (seq === mountSeq) reportError(err && err.message, err && err.stack);
      }
    };

    window.addEventListener("message", (e) => {
      const d = e.data;
      if (!d || d.channel !== CHANNEL) return;
      if (d.type === "init") {
        applyTheme(d.theme);
        if (d.analytics) void bootAnalytics(d.analytics);
        void mount(d.code);
      } else if (d.type === "set-theme") {
        // Re-theme in place — no mount(), so the app keeps all its state.
        applyTheme(d.theme);
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
  /* Track the theme via Quill's tokens (set on :root / .dark) so the page chrome
     flips with the host theme; fall back to light if the tokens haven't loaded. */
  body { font-family: ui-sans-serif, system-ui, -apple-system, sans-serif; color: var(--foreground, #111); background: var(--background, #fff); }
  #root { min-height: 100vh; }
</style>
</head>
<body>
<div id="root"></div>
<script type="module">${bootstrap}</script>
</body>
</html>`;
}

// The iframe CSP (third isolation layer). `connect-src` matters most: in view
// mode it is otherwise locked down so a published canvas can't phone home. When
// analytics/replay is on we open ONLY the PostHog ingest + assets hosts (so
// posthog-js can load its recorder and POST events/replay) — never arbitrary
// egress.
function contentSecurityPolicy(
  mode: SandboxMode,
  analyticsApiHost?: string,
): string {
  const esm = FREEFORM_ESM_HOST;
  // posthog-js posts events to the api host and loads the recorder from the
  // region assets host; allow both. Wildcards cover PostHog Cloud regions; the
  // explicit api host covers self-hosted.
  const ph = analyticsApiHost
    ? `${analyticsApiHost} https://*.posthog.com https://*.i.posthog.com`
    : "";

  if (mode === "edit") {
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
      // so 'unsafe-eval' is required). Edit-mode ONLY — view mode keeps egress
      // locked and self-hosts styles instead.
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
  // view / published: self-hosted, frozen. Only egress is PostHog analytics.
  return [
    "default-src 'none'",
    `script-src 'unsafe-inline' blob: 'self' ${ph}`,
    "style-src 'unsafe-inline' 'self'",
    "font-src data: 'self'",
    "img-src data: blob: 'self'",
    `worker-src blob:`,
    `connect-src 'self' ${ph}`,
  ].join("; ");
}
