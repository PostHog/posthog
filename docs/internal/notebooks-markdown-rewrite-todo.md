# Notebooks Markdown Rewrite Todo

This tracks the project to rebuild notebooks around markdown storage,
first-class custom components, and collaborative editing.

Status: initial implementation through milestone 7 exists in
`frontend/src/lib/components/MarkdownNotebook/`.
Milestone 8 remains open for migration, product integration, rollout, and
production hardening.

## Goals

- [x] Build an in-house notebook editor component under `lib/components/`.
- [x] Store notebooks as a single markdown string.
- [x] Support custom notebook components embedded in markdown as JSX-like tags,
      for example `<Query query={...} />`.
- [x] Keep the editor experience close to current notebooks while hiding raw
      markdown syntax from users.
- [x] Expose a component API where `value` is the full markdown string and
      `onChange` receives the next full markdown string.
- [x] Make edits resilient to remote changes, conflict-free sync, and local
      cursor/selection preservation.
- [x] Add Storybook coverage for the core editing, viewing, component, embed,
      and collaboration states.

## Non-goals and constraints

- Do not depend on external frontend renderer or editor component frameworks.
- Utility libraries are acceptable for focused problems such as diffing, conflict
  resolution, parsing helpers, or CRDT data structures if they are worth the
  tradeoff.
- Users should edit rich notebook content, not markdown source.
- The internal representation must preserve enough structure to round-trip
  cleanly back to markdown.
- Do not regress the existing notebook component catalog, embeds, or
  add-component flow.

## Component model

- [x] Define the public editor API:
  - [x] `value: string`
  - [x] `onChange(nextValue: string): void`
  - [x] view/edit mode controls
  - [x] component registry input
  - [x] collaboration/sync integration points
- [x] Define a notebook component registry:
  - [x] tag name
  - [x] markdown serialization and parsing
  - [x] edit renderer
  - [x] view renderer
  - [x] toolbar/menu metadata
  - [x] validation for component props
- [x] Wrap rendered custom blocks in a shared notebook component shell:
  - [x] toggle between view and edit modes
  - [ ] expose selected state
  - [ ] support deletion and movement
  - [x] surface component-specific actions
- [x] Map current notebook blocks to markdown tags:
  - [x] Insights and queries use `<Query />` where possible
  - [x] Text blocks become markdown text
  - [x] Existing embeds remain supported
  - [x] Add dedicated tags for blocks that do not fit cleanly into `<Query />`

## Markdown and internal representation

- [x] Design the supported markdown subset:
  - [x] paragraphs
  - [x] headings
  - [x] bold
  - [x] italic
  - [x] underline
  - [x] links
  - [x] lists
  - [x] code spans and code blocks if needed
  - [x] blockquotes if needed
  - [x] embeds
  - [x] JSX-like custom component tags
- [x] Define the internal AST:
  - [x] stable node IDs
  - [x] text nodes
  - [x] inline formatting marks
  - [x] block nodes
  - [x] component nodes
  - [x] embed nodes
  - [x] unknown or invalid node handling
- [x] Build markdown to AST parsing.
- [x] Build AST to markdown serialization.
- [x] Preserve stable identity across parse cycles where content is unchanged.
- [x] Support graceful handling of malformed markdown or invalid component props.
- [x] Add fixture-based round-trip tests for markdown, AST, and serialized output.

## Incremental updates and diffing

- [x] Design an algorithm for reconciling a new incoming markdown string with
      the current AST.
- [x] Detect unchanged nodes and preserve React identity, cursor state, selection
      state, and component local state.
- [x] Handle inserted text.
- [x] Handle deleted text.
- [x] Handle modified text.
- [x] Handle inserted component tags.
- [x] Handle deleted component tags.
- [x] Handle modified component props.
- [x] Handle movement of blocks or components.
- [x] Add tests for local edits, remote edits, and mixed text/component changes.

## Editing experience

- [x] Build the main canvas editor.
- [x] Use contenteditable for text editing only where necessary.
- [x] Sanitize pasted or edited HTML into the supported internal AST.
- [x] Strip unsupported markup.
- [ ] Preserve expected text editing behavior:
  - [x] cursor movement
  - [x] multi-line selection
  - [ ] undo/redo
  - [x] paste
  - [x] copy
  - [x] drag selection
  - [ ] keyboard shortcuts
- [x] Render markdown structure visually:
  - [x] headings display as larger text
  - [x] bold displays as bold
  - [x] italic displays as italic
  - [x] underline displays as underline
  - [x] lists display as lists
- [x] Do not expose raw markdown syntax during normal editing.
- [x] Add inline formatting menu on text selection:
  - [x] bold
  - [x] italic
  - [x] underline
  - [x] heading style
  - [x] paragraph style
- [x] Add empty-line insertion affordance:
  - [x] show a `+` button on a brand new line
  - [x] hide the `+` button after interaction
  - [x] open the add-component menu on click
  - [x] open the add-component menu when typing `/`
- [x] Match the current notebooks add-component flow.
- [ ] Support keyboard and screen-reader accessibility for toolbars and component
      insertion.

## Components and embeds

- [x] Inventory all existing notebook components.
- [x] Inventory all existing supported embeds.
- [x] Define markdown tag format for each component and embed.
- [x] Implement `<Query />` for insights and query-backed blocks.
- [x] Implement additional tags for components that need distinct semantics.
- [x] Support component prop editing without exposing raw JSX to users.
- [x] Support component rendering in view mode.
- [x] Support component rendering in edit mode.
- [x] Add component-level validation and recoverable error UI.
- [x] Add Storybook stories for every registered component in view and edit mode.

## Collaboration and syncing

- [x] Define the collaboration model:
  - [x] CRDT, operational transform, or equivalent merge strategy
  - [x] conflict-free local and remote edits
  - [x] stable local selection during remote updates
  - [x] component state preservation during sync
- [x] Decide how the markdown string maps into the collaborative data model.
- [x] Support remote text edits without disrupting current local editing.
- [x] Support remote component insertions and deletions.
- [x] Support remote component prop changes.
- [x] Handle simultaneous edits to the same text range.
- [x] Handle simultaneous edits to the same component props.
- [x] Add tests for conflict scenarios.
- [x] Add Storybook or mocked collaboration demos.

## Persistence and migration

- [ ] Define the stored markdown format.
- [ ] Define conversion from existing notebook data to markdown.
- [ ] Define conversion or compatibility for existing notebooks during rollout.
- [ ] Preserve notebook history and sharing behavior.
- [ ] Add migration validation fixtures for real notebook shapes.
- [ ] Plan feature flag rollout.
- [ ] Plan fallback or rollback behavior.

## Storybook

- [x] Add stories for an empty notebook.
- [x] Add stories for text-only notebooks.
- [x] Add stories for headings and inline formatting.
- [x] Add stories for lists and links.
- [x] Add stories for `<Query />` blocks.
- [x] Add stories for every existing notebook component.
- [x] Add stories for embeds.
- [x] Add stories for malformed markdown recovery.
- [x] Add stories for invalid component props.
- [x] Add stories for view mode.
- [x] Add stories for edit mode.
- [x] Add stories for selection toolbar states.
- [x] Add stories for slash menu and `+` insertion.
- [x] Add stories for mocked remote collaboration updates.

## Open questions

- [ ] What exact markdown subset should be supported at launch?
- [ ] Should custom component props be stored as JSX expression syntax, JSON, or
      a constrained hybrid?
- [ ] How should stable node IDs be represented if the stored format is only
      markdown text?
- [ ] Which collaboration primitive should back conflict-free sync?
- [ ] How much of current notebook behavior must be preserved before beta?
- [ ] Which current embeds require special parsing or security handling?
- [ ] Should there be a raw markdown debug mode for staff or development only?

## Milestones

- [x] Milestone 1: component inventory, markdown format, and AST design.
- [x] Milestone 2: parser, serializer, and round-trip fixtures.
- [x] Milestone 3: text canvas editing with sanitized contenteditable input.
- [x] Milestone 4: custom component registry and `<Query />` support.
- [x] Milestone 5: current notebook component and embed parity.
- [x] Milestone 6: conflict-free sync prototype.
- [x] Milestone 7: Storybook coverage and UX polish.
- [ ] Milestone 8: migration plan, feature flag rollout, and beta readiness.
