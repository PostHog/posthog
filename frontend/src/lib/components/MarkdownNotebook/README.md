# MarkdownNotebook

A notebook editor that uses markdown as its storage format. The document model is parsed from and serialized back to markdown on every edit, so the markdown string is always the source of truth.

See [COMPONENTS.md](./COMPONENTS.md) for how to register embeddable components (`<Query ... />`-style tags).

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
| `editorTypes.ts` / `componentPanels.ts`                                                             | Internal shared types, constants, and component panel visibility state                                                                                    |
| `Editable*.tsx`, `renderNode.tsx`                                                                   | Per-block render components (text, list, table, code, AI prompt)                                                                                          |
| `NotebookComponentShell.tsx`, `InsertMenu.tsx`, `FormattingToolbar.tsx`, `InsertBoundaryButton.tsx` | Editor chrome                                                                                                                                             |

## Event architecture: one editing host

The canvas (`.MarkdownNotebook__canvas`) is a single `contenteditable` editing host. Block elements inside it (list items, table cells, code blocks) also carry `contenteditable`, but **nested contenteditable elements inside an editable region are not separate editing hosts** — in real browsers, keyboard and `beforeinput` events target the canvas, not the inner block.

Because of this, all editing behavior must be dispatched from root-level handlers based on the current selection:

- `handleRootEditableKeyDown` (canvas `onKeyDown`) — Tab indentation, Enter splits, Backspace/Delete semantics
- the native `beforeinput` capture listener — `insertParagraph`, `deleteContent*`, `historyUndo/Redo`
- `handleRootEditableInput` (canvas `onInput`) — syncing typed text back into the document model

These resolve the affected block with `getInlineEditableElementForSelection` and the `data-markdown-notebook-*` attributes. Do **not** add keyboard handlers to inner block components: they only fire in JSDOM tests (where events are dispatched directly on inner elements), so they create behavior that passes tests but never runs in the app.

## Sync model

The component receives two props: `value` (the local content owned by the caller, e.g. `notebookLogic.localContent`) and `remoteValue` (the latest known server content). Internally it tracks:

- `lastSerializedValueRef` — the last markdown emitted through `onChange`
- `lastBaseValueRef` — the last server state local edits were derived from; this is always a server-side value, never a local or merged one, since it is the common ancestor for the next three-way merge

When `remoteValue` changes it is merged with `mergeNotebookMarkdownChanges({ base, local, remote })`, and the merged document is committed without touching the merge base (the merge result still contains unsaved local changes). When `remoteValue` catches up with the local serialization (autosave echo), the component is fully synced; undo history is intentionally preserved in that case.

Save conflicts (HTTP 409) are resolved through the same path: `notebookLogic` reloads the fresh server content, which flows in as `remoteValue`, the editor merges and re-emits, and the save is retried against the new version.
