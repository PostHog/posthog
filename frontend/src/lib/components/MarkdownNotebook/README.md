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
| `documentModel.ts`                                                                                  | Pure document/block-level helpers: visual grouping, node predicates, input shortcuts, clipboard serialization                                             |
| `listModel.ts` / `tableModel.ts`                                                                    | Pure list and table structure operations (depth shifting, row/column normalization)                                                                       |
| `inlineContent.ts`                                                                                  | Pure inline-node operations: marks, links, splitting at offsets                                                                                           |
| `domSelection.ts`                                                                                   | DOM selection reading/writing: mapping `window.getSelection()` to nodes and back                                                                          |
| `registry.tsx`                                                                                      | Built-in component definitions (`Query`, `Image`, `Embed`, …) and the registry helpers                                                                    |
| `editorTypes.ts` / `componentPanels.ts`                                                             | Internal shared types, constants, and component panel visibility state                                                                                    |
| `Editable*.tsx`, `DividerBlock.tsx`, `renderNode.tsx`                                               | Per-block render components (text, list, table, code, divider, AI prompt)                                                                                 |
| `NotebookComponentShell.tsx`, `InsertMenu.tsx`, `FormattingToolbar.tsx`, `InsertBoundaryButton.tsx` | Editor chrome                                                                                                                                             |

## Supported markdown

Inline: bold (`**`), italic (`*`), underline (`<u>`), strikethrough (`~~`), inline code, links, and hard breaks. Blocks: paragraphs, headings (`#`–`######` parse and round-trip; the UI offers H1–H3), blockquotes (including quoted lists), ordered/unordered lists with nesting, GFM tables with column alignment, fenced code blocks (language tag preserved), dividers (`---`/`***`/`___`, stored as a reserved `Divider` component tag), images (`![alt](src)`, stored as the `Image` component), and JSX-like component tags.

## Visual grouping

Consecutive text-like blocks (paragraphs, headings, lists, blockquotes, code blocks) render inside one shared card surface — a _text group_ (`getMarkdownNotebookVisualGroups` in `documentModel.ts`). Within a group, blockquote runs and code blocks form their own tinted sub-surfaces (`MarkdownNotebookTextSurface`: `text` | `quote` | `code`); a surface that starts or ends its group stretches flush to the card edge. Components, tables, and dividers render as standalone rows between groups.

Code blocks render a non-editable line-number gutter next to the editable `<pre>`. Gutter numbers are absolutely positioned at line tops measured from the DOM (wrapped lines hang without numbers), so the gutter never participates in selection, copy, or text offsets. A trailing `<br>` sentinel keeps trailing blank lines visible; it contributes nothing to `textContent`, which keeps offsets stable.

## Event architecture: one editing host

The canvas (`.MarkdownNotebook__canvas`) is a single `contenteditable` editing host. Block elements inside it (list items, table cells, code blocks) also carry `contenteditable`, but **nested contenteditable elements inside an editable region are not separate editing hosts** — in real browsers, keyboard and `beforeinput` events target the canvas, not the inner block.

Because of this, all editing behavior must be dispatched from root-level handlers based on the current selection:

- `handleRootEditableKeyDown` (canvas `onKeyDown`) — Tab indentation, Enter splits, Backspace/Delete semantics, ArrowDown below a trailing code block
- the native `beforeinput` capture listener — `insertParagraph`/`insertLineBreak` (inside code blocks these insert a literal `\n` through the model, since the browser default inserts `<br>` elements that are invisible to `textContent`), `deleteContent*`, `historyUndo/Redo`
- `handleRootEditableInput` (canvas `onInput`) — syncing typed text back into the document model
- `handleNotebookKeyDown` (notebook root `onKeyDownCapture`) — Cmd/Ctrl shortcuts: bold/italic/underline (`B`/`I`/`U`), strikethrough (`Shift+X`), scoped select-all (`A`), copy of a focused component (`C`)

These resolve the affected block with `getInlineEditableElementForSelection` and the `data-markdown-notebook-*` attributes. Do **not** add keyboard handlers to inner block components: they only fire in JSDOM tests (where events are dispatched directly on inner elements), so they create behavior that passes tests but never runs in the app.

## Sync model

The component receives two props: `value` (the local content owned by the caller, e.g. `notebookLogic.localContent`) and `remoteValue` (the latest known server content). Internally it tracks:

- `lastSerializedValueRef` — the last markdown emitted through `onChange`
- `lastBaseValueRef` — the last server state local edits were derived from; this is always a server-side value, never a local or merged one, since it is the common ancestor for the next three-way merge

When `remoteValue` changes it is merged with `mergeNotebookMarkdownChanges({ base, local, remote })`, and the merged document is committed without touching the merge base (the merge result still contains unsaved local changes). When `remoteValue` catches up with the local serialization (autosave echo), the component is fully synced; undo history is intentionally preserved in that case.

Save conflicts (HTTP 409) are resolved through the same path: `notebookLogic` reloads the fresh server content, which flows in as `remoteValue`, the editor merges and re-emits, and the save is retried against the new version.
