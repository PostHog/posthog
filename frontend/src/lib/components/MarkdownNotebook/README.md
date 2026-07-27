# MarkdownNotebook

A notebook editor that uses markdown as its storage format. The document model is parsed from and serialized back to markdown on every edit, so the markdown string is always the source of truth.

See [COMPONENTS.md](./COMPONENTS.md) for how to register embeddable components (`<Query ... />`-style tags) and [TODO.md](./TODO.md) for open work.

## Module layout

| Module                                                                                              | Responsibility                                                                                                                                            |
| --------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `MarkdownNotebook.tsx`                                                                              | The editor component: document state, commit/undo, selection restoration, keyboard/input dispatch, drag/copy/paste, insert menu and toolbar orchestration |
| `markdown.ts`                                                                                       | Markdown ↔ `NotebookDocument` parser and serializer, stable node ID assignment                                                                            |
| `reconcile.ts`                                                                                      | Preserves node identity across re-parses so the caret and DOM survive autosave echoes                                                                     |
| `collaboration.ts`                                                                                  | Three-way merge of base/local/remote markdown for autosave conflicts and realtime updates                                                                 |
| `remoteCarets.tsx`                                                                                  | Remote caret presence: cross-client caret coordinates (node index + text offset) and the positioned caret overlay                                         |
| `documentModel.ts`                                                                                  | Pure document/block-level helpers: visual grouping, node predicates, input shortcuts, clipboard serialization                                             |
| `listModel.ts` / `tableModel.ts`                                                                    | Pure list and table structure operations (depth shifting, row/column normalization)                                                                       |
| `inlineContent.ts`                                                                                  | Pure inline-node operations: marks, links, splitting at offsets                                                                                           |
| `domSelection.ts`                                                                                   | DOM selection reading/writing: mapping `window.getSelection()` to nodes and back                                                                          |
| `registry.tsx`                                                                                      | Built-in component definitions (`Query`, `Image`, `Embed`, …) and the registry helpers                                                                    |
| `editorTypes.ts` / `componentPanels.ts`                                                             | Internal shared types, constants, and component panel visibility state                                                                                    |
| `Editable*.tsx`, `DividerBlock.tsx`, `renderNode.tsx`                                               | Per-block render components (text, list, table, code, divider, AI prompt)                                                                                 |
| `NotebookComponentShell.tsx`, `InsertMenu.tsx`, `FormattingToolbar.tsx`, `InsertBoundaryButton.tsx` | Editor chrome                                                                                                                                             |

## Supported markdown

Inline: bold (`**`/`__`), italic (`*`/`_`, underscores only at word boundaries), underline (`<u>`), strikethrough (`~~`), inline code, links (http/https only; balanced parentheses in hrefs supported), hard breaks, ref anchors (`<ref id="x">highlighted text</ref>`, lowercase inline tags so they can never collide with uppercase component tags), and mentions (`<mention id="5">@Name</mention>`; the text is the display label, the id is the member). Blocks: paragraphs, headings (`#`–`######` parse and round-trip; the UI offers H1–H3), blockquotes (including quoted headings — `> ## Heading` — and quoted lists), ordered/unordered lists with nesting, GFM task lists (`- [ ]`/`- [x]` on bullet items; the checkbox replaces the bullet and `1. [x]` stays literal), GFM tables with column alignment (header and body rows must start with `|`), fenced code blocks (language tag preserved; the serializer picks a fence longer than any backtick run in the content), dividers (`---`/`***`/`___`, stored as a reserved `Divider` component tag), images (`![alt](src)`, stored as the `Image` component), and JSX-like component tags.

### Round-trip guarantee

`parse(serialize(doc))` must preserve the document: the serializer backslash-escapes every character the inline parser would interpret (`escapeInlineMarkdownText`, kept in sync with `INLINE_ESCAPABLE_CHARS`), and `escapeMarkdownLineStart` protects text lines that would otherwise re-parse as a different block type (headings, lists, blockquotes, dividers, component tags). Source text is never dropped: an unterminated component tag stops at the first blank line and degrades to a paragraph, and a component tag with malformed props serializes back from its `raw` source until it is edited. `markdownRoundTrip.test.ts` enforces this with a generated-document fixpoint test — extend it when adding syntax.

## Visual grouping

Consecutive text-like blocks (paragraphs, headings, lists, blockquotes, code blocks) render inside one shared card surface — a _text group_ (`getMarkdownNotebookVisualGroups` in `documentModel.ts`). Within a group, blockquote runs and code blocks form their own tinted sub-surfaces (`MarkdownNotebookTextSurface`: `text` | `quote` | `code`); a surface that starts or ends its group stretches flush to the card edge. Components, tables, and dividers render as standalone rows between groups.

Code blocks render a non-editable line-number gutter next to the editable `<pre>`. Gutter numbers are absolutely positioned at line tops measured from the DOM (wrapped lines hang without numbers), so the gutter never participates in selection, copy, or text offsets. A trailing `<br>` sentinel keeps trailing blank lines visible; it contributes nothing to `textContent`, which keeps offsets stable.

## Event architecture: one editing host

The canvas (`.MarkdownNotebook__canvas`) is a single `contenteditable` editing host. Block elements inside it (list items, table cells, code blocks) also carry `contenteditable`, but **nested contenteditable elements inside an editable region are not separate editing hosts** — in real browsers, keyboard and `beforeinput` events target the canvas, not the inner block.

Because of this, all editing behavior must be dispatched from root-level handlers based on the current selection:

- `handleRootEditableKeyDown` (canvas `onKeyDown`) — Tab indentation, Enter splits, Backspace/Delete semantics, ArrowDown below a trailing code block
- the native `beforeinput` capture listener — `insertParagraph`/`insertLineBreak` (inside code blocks these insert a literal `\n` through the model, since the browser default inserts `<br>` elements that are invisible to `textContent`), `deleteContent*`, `historyUndo/Redo`, and a last-resort guard that cancels any unclaimed native range edit crossing inline-editable boundaries — the browser would otherwise restructure React-managed elements in place (e.g. merge two `<li>`s) and the next React commit would crash with `removeChild` DOM exceptions
- `handleRootEditableInput` (canvas `onInput`) — syncing typed text back into the document model
- `handleNotebookKeyDown` (notebook root `onKeyDownCapture`) — Cmd/Ctrl shortcuts: bold/italic/underline (`B`/`I`/`U`), strikethrough (`Shift+X`), scoped select-all (`A`), copy of a focused component (`C`)

These resolve the affected block with `getInlineEditableElementForSelection` and the `data-markdown-notebook-*` attributes. Do **not** add keyboard handlers to inner block components: they only fire in JSDOM tests (where events are dispatched directly on inner elements), so they create behavior that passes tests but never runs in the app.

## Sync model

The component receives two props: `value` (the local content owned by the caller, e.g. `notebookLogic.localContent`) and `remoteValue` (the latest known server content). Internally it tracks:

- `lastSerializedValueRef` — the last markdown emitted through `onChange`
- `lastBaseValueRef` — the last server state local edits were derived from; this is always a server-side value, never a local or merged one, since it is the common ancestor for the next three-way merge

When `remoteValue` changes it is merged with `mergeNotebookMarkdownChanges({ base, local, remote })`, and the merged document is committed without touching the merge base (the merge result still contains unsaved local changes). When `remoteValue` catches up with the local serialization (autosave echo), the component is fully synced; undo history is intentionally preserved in that case.

Save conflicts (HTTP 409) are resolved through the same path: `notebookLogic` reloads the fresh server content, which flows in as `remoteValue`, the editor merges and re-emits, and the save is retried against the new version.

## Debug session recorder

The debug drawer (`showDebug`) has a Log button that records an editing session as JSONL: every keystroke, mouse, input, and clipboard event on the notebook (capture phase), deduplicated selection snapshots, and every document commit with the resulting markdown — plus remote merges with their base/local/remote inputs and conflicts. Stop downloads the session as a `.log` file, built to be handed to an agent (or a human) to reconstruct exactly what the editor did and why.

If the editor crashes while a recording is in flight, the log downloads itself instead of being lost: a `crash` entry (error, stack, current markdown) is appended and the file is saved immediately — whether the crash is an uncaught error in an event handler (window `error` listener) or a React render/commit error (`MarkdownNotebookCrashReporter`, which flushes the log and rethrows so the app's error boundary still takes over). Unhandled promise rejections are logged as entries but don't end the session.

## Inline discussion comments

A Google Docs-style comment thread is two paired pieces of markdown: an inline `<ref id="banana">highlighted text</ref>` anchor (a multi-block selection wraps each block's range in the same id) and a `<Comment ref="banana" replies={[…]} />` block placed right above the first block holding the highlight. When threads are present and the container is wide enough, the canvas reserves a right gutter (`--markdown-notebook-comment-gutter`) and pushes the text column left; each thread row keeps zero height so the card hangs in the gutter level with its content. Below `COMMENT_GUTTER_MIN_CONTAINER_WIDTH_PX` the threads flow inline as right-aligned cards. Replies live in the markdown itself as an id-keyed array, so two people replying at the same time merge by union (`mergeIdKeyedArrayPropValues` in `collaboration.ts`) instead of clobbering each other.

Deletion is intentionally asymmetric (`removeNotebookNodesWithRefCleanup` in `documentModel.ts`): deleting the comment thread also unwraps its `<ref>` highlight, but removing the highlight (or the text holding it) leaves the thread in place — it contains people's replies and must be deleted on its own.

The `Comment` tag also has an authorial-note flavor (`text` prop) that serializes as a plain `<!-- … -->` markdown comment; `isDiscussionCommentProps` in `markdown.ts` is the discriminator.
