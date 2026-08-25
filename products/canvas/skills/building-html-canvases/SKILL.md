---
name: building-html-canvases
description: >
  Author a PostHog canvas with semantic HTML, CSS, and direct browser APIs — documents, articles,
  generative graphics, 2D canvas and WebGL experiences, and focused experiments where React
  components add no useful structure. Use after building-canvases has routed a canvas request to a
  plain-HTML/browser-API implementation. Covers the thin component wrapper the current runtime
  requires, styling and theming without Quill, drawing surfaces, and animation/cleanup patterns.
---

# Building HTML canvases

Some canvases are documents or graphics programs, not applications: a written report, a diagram,
a generative-art piece, a WebGL scene. For these, semantic HTML, CSS, and direct browser APIs are
the right tools — don't force Quill components or React state onto a static page.

## The wrapper the current runtime requires

Every canvas keeps `src/canvas.tsx` as its mounted React entry component (default export, no
props). Keep the React layer as a thin shell and write the
experience in HTML/CSS/browser APIs inside it:

- A document is JSX that is effectively semantic HTML — `<article>`, headings, lists, tables,
  figures — with a `<style>` block for typography and layout. Write real, specific copy.
- A drawing/WebGL program renders a `<canvas>` element and drives it imperatively from a
  `useEffect` via a ref: get the 2D/WebGL context, run the setup and render loop there.
- Clean up in the effect's return: cancel `requestAnimationFrame` loops, remove listeners, and
  release contexts, so theme switches and remounts don't leak or double-run.
- Mixing tiers is fine: a mostly static page can mount one interactive island, and a data board
  can hand a chart's `<canvas>` to imperative code while React owns the chrome.

The import allowlist still applies (react, react-dom, @posthog/quill, recharts, lucide-react,
dayjs) — browser globals (`document`, `CanvasRenderingContext2D`, `WebGLRenderingContext`,
`requestAnimationFrame`, `IntersectionObserver`, Web Audio, etc.) need no import. Three.js and
other npm graphics libraries are not yet loadable; write against raw WebGL or 2D canvas until the
build pipeline's dependency admission ships.

## Styling and theme without Quill

- Size the outermost JSX/HTML element to the iframe viewport with `h-screen` or `height: 100vh`.
  Do not use `h-full` or `height: 100%` on that root: a published canvas's artifact shell gives
  its `html`, `body`, and `#root` elements no explicit height, so percentage height collapses to
  the content height. Descendants may use percentage height after the outermost element establishes
  the viewport height.
- Use Tailwind utilities and/or a `<style>` block (keyframes and complex selectors are fine).
- The host toggles a `.dark` class on the document root when the user's PostHog theme changes.
  Define your colors as CSS variables under `:root { … }` with overrides under `html.dark { … }`,
  or use theme token utilities (`bg-background`, `text-foreground`, `border-border`) — never a
  light-only hardcoded color.
- For canvas/WebGL drawing colors, read the resolved token at runtime
  (`getComputedStyle(document.documentElement).getPropertyValue("--primary")`) or your own CSS
  variables, and re-read on theme change if the scene is long-lived.

## Rules that still apply

- No `fetch()`/`XMLHttpRequest`, no `<script>` tags, no dynamic `import()`, no remote assets —
  the sandbox blocks them. PostHog data comes only through the `ph` bridge (see the
  `querying-canvas-data` skill), including `ph.capture` for interaction analytics.
- A document that states PostHog numbers must make each one verifiable: an insight-backed number
  links its saved insight through `ph.openExternal` (URL from the `generate-app-url` MCP tool,
  from a click); an ad-hoc `ph.query` number discloses the exact query that ran in a `<details>`
  element beside the claim — see "Verifiability" in `querying-canvas-data`.
- External links go through `ph.openExternal(url)` (posthog.com origins only), from a user
  interaction.
- Validate and publish through the canvas tools as described in `validating-and-publishing-canvases`.
