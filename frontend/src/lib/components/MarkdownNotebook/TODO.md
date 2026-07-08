# MarkdownNotebook — open work

The markdown notebook rewrite (markdown storage, custom component tags, conflict-free sync) is implemented in this folder and wired into the notebooks scene via `frontend/src/scenes/notebooks/Notebook/markdownNotebookV2.ts`. What remains is rollout, migration, and a few editor gaps.

## Rollout and migration

- With the `MARKDOWN_NOTEBOOKS` flag on, everything is markdown: existing notebooks render through the markdown editor (converted at render time, persisted on first edit), and new notebooks, template copies, the scratchpad, canvases, and Max-created notebooks are created in the markdown format. With the flag off, notebooks whose stored content is already markdown still use the markdown editor.
- Batch conversion of existing notebooks (`convertNotebookContentToMarkdown`) needs migration validation fixtures built from real production notebook shapes, beyond the unit-test coverage in `notebookUpgradeDialog.test.tsx`.
- Verify notebook history and sharing behavior survive the upgrade (history diffs against TipTap JSON snapshots predating the conversion).
- Rollback: `convertMarkdownToNotebookContent` (markdownNotebookDowngrade.ts) converts markdown back to TipTap content. Known one-way losses are documented in its module docstring (discussion reply threads, AI prompts, table alignments) — wire it into a user-facing rollback flow if needed.

## Editor gaps

- (none currently tracked — accessibility for the toolbar/insert menu, comments on code block selections, and canvas drag-and-drop at the drop position have shipped)

## Open questions

- Should custom component props remain JSX-expression syntax in stored markdown, or move to a constrained JSON form?
- Which embeds need special parsing or security review before general availability?
- Should the raw markdown debug drawer (`showDebug`) be staff-only in production?
