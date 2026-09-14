# Notebook collaboration

Readers can scroll through a notebook while collaborators edit it.
Incoming edits update the content and keep the local caret attached to the same text without scrolling its block into view.
This also applies to incoming notebook content replacements, such as AI edits.
Local editing actions, including Enter to create a new row, still bring the active row into view.

The editor records `preserveViewport` on selection restoration requests created by incoming updates.
Selection restoration uses `preventScroll` for browser focus calls and skips explicit scrolling for those requests.
If focus has moved outside the notebook, incoming updates leave it there.

To check this behavior in Storybook, place the caret in a notebook paragraph, scroll it out of view, and apply a remote edit.
The visible section should stay in place while the content and caret update.
