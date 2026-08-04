// The package whitelist for freeform-React canvases (Q16: curated, PostHog-
// anchored). Every entry is a package the agent may import; anything else is
// rejected by the static check below. Keep this list SMALL — each entry is
// hosting surface (in public mode), bundle weight, and attack surface. Expand
// only on observed demand.
//
// `esm` is the render-time module URL used in EDIT mode (Q2/Q3: in-browser Babel
// + esm.sh CDN). In published/view mode these resolve to self-hosted, frozen
// copies instead (Phase 2: the publish/bundle step rewrites the import map); the
// names stay the same so canvas code is identical across tiers.
export interface WhitelistEntry {
  /** The bare import specifier the agent writes, e.g. "recharts". */
  name: string;
  /** Pinned version. Frozen so a canvas can't drift onto a new major. */
  version: string;
  /** esm.sh URL for edit-mode render (CDN). */
  esm: string;
}

const ESM = "https://esm.sh";

// One source of truth for the Quill version — used by both the import-map entry
// (the JS module) and the stylesheet URLs the iframe links (see below).
const QUILL_VERSION = "0.3.0-beta.18";

// `?external=react,react-dom` keeps every dependent bound to the ONE react the
// import map provides, instead of esm.sh bundling its own copy (which breaks
// hooks across module boundaries — "invalid hook call").
export const FREEFORM_WHITELIST: WhitelistEntry[] = [
  { name: "react", version: "19.0.0", esm: `${ESM}/react@19.0.0` },
  {
    name: "react-dom",
    version: "19.0.0",
    esm: `${ESM}/react-dom@19.0.0?external=react`,
  },
  {
    name: "react-dom/client",
    version: "19.0.0",
    esm: `${ESM}/react-dom@19.0.0/client?external=react`,
  },
  // PostHog's own design system — already built + self-hosted, so it's the
  // cheapest dependency and keeps shared canvases visually on-brand.
  {
    name: "@posthog/quill",
    version: QUILL_VERSION,
    esm: `${ESM}/@posthog/quill@${QUILL_VERSION}?external=react,react-dom`,
  },
  // One charting library (the conventional React pick).
  {
    name: "recharts",
    version: "2.15.0",
    esm: `${ESM}/recharts@2.15.0?external=react,react-dom`,
  },
  // The icon set (named exports, e.g. `import { Calendar, RefreshCw } from "lucide-react"`).
  {
    name: "lucide-react",
    version: "1.21.0",
    esm: `${ESM}/lucide-react@1.21.0?external=react`,
  },
  // One formatting/date util.
  { name: "dayjs", version: "1.11.13", esm: `${ESM}/dayjs@1.11.13` },
];

// The CDN host the edit-mode import map (and Babel) load from. The iframe CSP
// must allow this in edit mode; view/published mode self-hosts and forbids it.
export const FREEFORM_ESM_HOST = ESM;

// Quill stylesheets the iframe must <link> for its components to render styled.
// Quill ships a self-contained compiled sheet (BEM `.quill-*` classes — NO
// Tailwind build needed) plus its design tokens; the sandbox has no build step,
// so without these every Quill component renders unstyled (which is what forced
// agents to inline raw hex). Order matters: tokens + colors define the CSS vars,
// then the component styles consume them. CSP `style-src` already allows the CDN.
export const FREEFORM_QUILL_CSS_URLS = [
  `${ESM}/@posthog/quill@${QUILL_VERSION}/tokens.css`,
  `${ESM}/@posthog/quill@${QUILL_VERSION}/color-system.css`,
  `${ESM}/@posthog/quill@${QUILL_VERSION}/base.css`,
  `${ESM}/@posthog/quill@${QUILL_VERSION}/primitives.css`,
];

// The in-browser transpiler (Q2), imported as ESM so egress stays on one host.
export const FREEFORM_BABEL_URL = `${ESM}/@babel/standalone@7.26.4`;

// posthog-js, booted by the runtime (not the agent) to power in-iframe analytics
// + session replay. Edit mode loads it from the CDN; the published tier will
// self-host it in the bundle. Pinned so a canvas can't drift onto a new major.
export const FREEFORM_POSTHOG_JS_URL = `${ESM}/posthog-js@1.205.0`;

// Names the agent is allowed to import. Subpath imports (e.g. "dayjs/plugin/x")
// are allowed when their package root is whitelisted AND the exact subpath is
// listed; we keep it strict (exact-match only) so a subpath can't smuggle in an
// unreviewed entry point.
const ALLOWED_SPECIFIERS = new Set(FREEFORM_WHITELIST.map((e) => e.name));

// The import map handed to the iframe so bare specifiers resolve to the pinned
// modules. Edit mode -> esm.sh; view mode (Phase 2) will pass self-hosted URLs.
export function buildImportMap(): { imports: Record<string, string> } {
  const imports: Record<string, string> = {};
  for (const entry of FREEFORM_WHITELIST) imports[entry.name] = entry.esm;
  // The automatic JSX runtime compiles `<div/>` to imports of these; canvases
  // never write them by hand, so they're not in the whitelist, but they must
  // resolve for any JSX to run.
  imports["react/jsx-runtime"] = `${ESM}/react@19.0.0/jsx-runtime`;
  imports["react/jsx-dev-runtime"] = `${ESM}/react@19.0.0/jsx-dev-runtime`;
  return { imports };
}

export interface ImportCheckResult {
  ok: boolean;
  /** Human-readable reasons the code was rejected (empty when ok). */
  violations: string[];
}

// Matches static module specifiers, which appear either as `from "spec"`
// (import-with-bindings and export-from) or a bare side-effect `import "spec"`.
// Anchoring on `from`/`import` (rather than "any quoted string following an
// import/export keyword") avoids flagging ordinary string literals such as
// `export default function App() { const s = "hi"; }`. Captures the specifier in
// group 1 or 2. Note: being regex-based it can still be fooled by the literal
// text `from "x"` inside a string/JSX — a fully correct check would parse the
// AST (deferred; this check isn't wired into save/publish yet).
const STATIC_IMPORT_RE =
  /\bfrom\s*["']([^"']+)["']|\bimport\s*["']([^"']+)["']/g;

// Patterns we reject outright regardless of specifier (Q9): dynamic import()
// dodges static analysis; require()/importScripts pull arbitrary modules; inline
// <script> and javascript: URLs are out-of-band code the import check can't see.
const FORBIDDEN_PATTERNS: { re: RegExp; reason: string }[] = [
  { re: /\bimport\s*\(/, reason: "dynamic import() is not allowed" },
  { re: /\brequire\s*\(/, reason: "require() is not allowed" },
  { re: /\bimportScripts\s*\(/, reason: "importScripts() is not allowed" },
  { re: /<script\b/i, reason: "inline <script> is not allowed" },
];

/**
 * Statically verify that freeform canvas code imports only whitelisted packages
 * and uses no out-of-band code-loading. Intended as the enforcement point (Q9)
 * at save AND publish — but NOT yet wired into the save path (the autosave in
 * freeformChatStore persists code without calling this). For now it is exercised
 * only by tests; wiring it in is a follow-up (and should land with the regex's
 * string/JSX false-positive limitation addressed, ideally via AST parsing).
 * Deliberately conservative — when in doubt it rejects. A relative import (./x)
 * is rejected because a canvas is a single file with no sibling modules.
 */
export function checkFreeformImports(code: string): ImportCheckResult {
  const violations: string[] = [];

  for (const { re, reason } of FORBIDDEN_PATTERNS) {
    if (re.test(code)) violations.push(reason);
  }

  for (const match of code.matchAll(STATIC_IMPORT_RE)) {
    const specifier = match[1] ?? match[2];
    if (!specifier) continue;
    if (!isAllowedSpecifier(specifier)) {
      violations.push(`import of non-whitelisted module "${specifier}"`);
    }
  }

  return { ok: violations.length === 0, violations };
}

function isAllowedSpecifier(specifier: string): boolean {
  return ALLOWED_SPECIFIERS.has(specifier);
}
