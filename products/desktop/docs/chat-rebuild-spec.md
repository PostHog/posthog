# ChatX Thread Rebuild — Build Spec

Status: in progress. Source of decisions: grilling session 2026-06-27.

## Thesis

Replace the virtualized thread (`ConversationView` + `VirtualizedList`) with shadcn
**Base-UI** chat primitives, renamed `ChatX`. Non-virtualized, `content-visibility: auto`,
minimal DOM, close to the shadcn examples. Primitives are built in **quill**; the app-side
thread is rebuilt in the **code** repo.

## Provenance

The primitives are vendored from the shadcn `base-mira` registry:

- `https://ui.shadcn.com/r/styles/base-mira/{message-scroller,message,bubble,marker,attachment}.json`
- The scroll **engine** is the published headless package `@shadcn/react` (MIT, exports
  `./message-scroller`). The styled file is a thin wrapper — same shape as quill's
  `Badge` wrapping `@base-ui/react`. We take `@shadcn/react` as a runtime dep of the
  quill primitives package and wrap it in quill conventions.

## Where

- **Primitives**: `posthog/packages/quill/packages/primitives/src/chat-*.tsx`
  (+ colocated `chat-*.css`, `chat-*.stories.tsx`), exported from `index.ts`.
  Conventions: `useRender` / `mergeProps` / `cva` / `data-quill` / `cn` from `./lib/utils`,
  4-space indent, single quotes.
- **App thread**: code repo `packages/ui` — new `<ChatThread>` replacing `ConversationView`.
- Flow: build in quill → local-link → integrate → publish beta → bump catalog.

## Primitives (v1 = four)

1. **ChatMessageScroller** (Provider / Root / Viewport / Content / Item / Button + 3 hooks).
   Thin wrap of `@shadcn/react/message-scroller`. Non-virtualized. `autoScroll`,
   `defaultScrollPosition="end"`, `scrollPreviousItemPeek≈64`, `scrollAnchor` on
   turn-start items. Imperative scroll state via data-attrs; no React state on scroll.
2. **ChatMessage** (Group / Avatar / Content / Header / Footer). `align="start|end"`.
   Avatar first-class, omitted in our render.
3. **ChatBubble** (Content / Reactions / Group). Assistant = `ghost` (no bg, full-width);
   user = filled.
4. **ChatMarker** (Icon / Content) — the recursive one. **Diverges from stock shadcn
   Marker**: when given a `body`, renders as a Base-UI Collapsible — hover shows a chevron
   + `bg-fill-hover`, click toggles, expanded renders the body. No body → flat status line
   (stock shadcn). Uncontrolled `defaultOpen` + optional `open` / `onOpenChange`.
   Pairs with `Spinner` + shimmer for live state.

Deferred: `ChatAttachment` (except trivial mention chips), `BubbleReactions`.

## Mapping (app layer)

- **User turn** → `ChatMessage align="end"` → filled `ChatBubble` → text (+ mention chips).
- **Assistant turn** → `ChatMessage align="start"` → `ghost ChatBubble` → bare markdown.
- **Single tool** → `ChatMarker` with `body` = injected detail (`<ReadContent/>`,
  `<EditDiff/>` — reused existing renderers; primitive is chrome-only).
- **Tool group (completed turn)** → summary `ChatMarker` ("Read 3 files · Edited 1") whose
  `body` = the per-tool child `ChatMarker`s.
- **Status / thought / error / compact / cancelled** → `ChatMarker`
  (`default` / `border` / `separator`).
- **MCP app iframes** → top-level rows, outside grouping, IntersectionObserver
  mount/unmount (no state preservation — acceptable).

## Grouping / collapse

- `mode={all|partial|none}` on **`<ChatThread>`** (app), not the primitive. App maps
  mode → per-marker `defaultOpen`: `none`→true, `all`→false, `partial`→`isActiveTurn`.
- **Live→complete**: live turn renders expanded markers (Spinner/shimmer); on completion
  the grouper **swaps row identity** → one collapsed summary marker mounts fresh. Keep
  `createIncrementalThreadGrouper`. No controlled-state flipping.

## Escape hatch (heavy rows)

Heavy rows opt into IntersectionObserver mount/unmount + placeholder. Off-screen MCP apps
unmount. `content-visibility: auto` saves paint, not React mount cost — this caps live
iframe processes.

## Anchoring / streaming

- Anchor = user message when present, else turn's first assistant row; `scrollAnchor` on
  those items only.
- `content-visibility: auto` + tuned `contain-intrinsic-size` per row type. Accept-and-tune
  for v1; leave a seam for a measured-size cache if the 1000-turn stress shows drift.

## Build order

1. Scroller + dummy rows + 1000-turn stress story (prove thesis).
2. `ChatMarker` (all variants / fill levels).
3. `ChatMessage` + `ChatBubble`.
4. Link → `<ChatThread>` (parse→group→primitives, `mode`, MCP mounting) behind existing composer.
5. Stress real thread, tune sizes.

Each primitive ships `*.stories.tsx` with shadcn-shaped fixtures.

## Kept untouched

Existing composer; event→item parse; optimistic merge; incremental grouper; tool detail renderers.
