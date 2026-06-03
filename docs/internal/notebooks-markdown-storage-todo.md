# Markdown-backed notebooks todo

## Research summary

- Current saved notebooks use `posthog_notebook.content` as ProseMirror/Tiptap JSON, `text_content` for search, and `version` for optimistic concurrency.
- The collaboration path is ProseMirror-specific: frontend sends `steps` to `/collab/save/`, Redis streams those steps for SSE, and the API persists the full JSON document after accepting the step range.
- The existing AI `create_notebook` tool already asks the model for markdown, but saved notebooks are immediately transformed into Tiptap JSON via `blocks_to_tiptap_doc`.
- MCP currently exposes generated CRUD tools plus a hand-written `notebook-edit` tool that edits ProseMirror JSON and saves through `/collab/save/`.
- `origin/notebook-mcp-ai-vitamins` has useful `<query>` parsing and richer MCP edit ideas, but it still centers on converting markdown into ProseMirror JSON and should not be copied wholesale.

## Storage contract

- Add a secondary durable field for markdown-backed notebooks.
- Add a discriminator so clients can tell legacy JSON notebooks from markdown-backed notebooks.
- Keep legacy JSON notebooks editable through the existing ProseMirror/collab path.
- New notebooks default to markdown storage when markdown content is provided.
- The API should return both canonical storage state and a display JSON document so existing rich nodes continue rendering while the frontend migration happens.

## Markdown syntax

- Markdown text remains normal markdown.
- `<Query>{...}</Query>` embeds a `ph-query` node with the JSON query payload.
- `<Query title="...">{...}</Query>` preserves the notebook node title.
- Legacy lower-case `<query>` should keep working for agents and MCP.
- Existing resource nodes should get explicit tags over time, starting with common saved resource nodes such as `<FeatureFlag id="..." />`, `<Experiment id="..." />`, `<Survey id="..." />`, `<Cohort id="..." />`, `<Person id="..." />`, `<Group id="..." />`, and `<SessionReplay id="..." />`.

## Implementation checklist

- [x] Add backend model fields and migration for markdown storage.
- [x] Add backend markdown conversion helpers for ProseMirror JSON <-> markdown.
- [x] Extend notebook serializers and API actions for markdown content and conversion/debugging.
- [x] Update frontend notebook types and save/load logic to use markdown-backed mode when present.
- [x] Add development/debug controls in the notebook UI showing storage mode and conversion helpers.
- [x] Keep old ProseMirror collab save path for legacy notebooks.
- [x] Add a markdown collab/save path for markdown-backed notebooks.
- [x] Update MCP notebook create/edit tools to prefer markdown and fall back to JSON for legacy notebooks.
- [x] Update AI notebook save path to store markdown-backed notebooks.
- [x] Add backend, frontend, and MCP tests for conversion and mode-specific save behavior.
- [x] Run targeted tests and type generation/checks.

## Progress log

- 2026-06-03: Researched current model/API/frontend/MCP/AI paths and compared `origin/notebook-mcp-ai-vitamins` at a high level.
- 2026-06-03: Added `content_storage` and `markdown_content`, markdown conversion helpers, `markdown/save`, `debug/convert`, and focused backend tests.
- 2026-06-03: Added frontend markdown serialization, markdown-backed save path, legacy JSON save preservation, local-only debug storage controls, and default markdown-backed notebook creation.
- 2026-06-03: Updated AI notebook persistence to save canonical markdown-backed notebooks and updated MCP create/edit tooling for markdown-first notebooks.
- 2026-06-03: Regenerated OpenAPI/frontend/MCP artifacts so generated notebook schemas include markdown storage fields and actions.
- 2026-06-03: Verified with focused backend tests, the full notebook API suite, markdown serializer Jest tests, OpenAPI generation, migration checks, frontend TypeScript, MCP typecheck/tool-name lint, and Python lint on touched files.
