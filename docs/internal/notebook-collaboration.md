# Notebook collaboration

Readers can scroll through a notebook while collaborators edit it.
Incoming edits keep the local caret attached to its text without scrolling that block into view or moving focus from another control.
Incoming content replacements, such as AI edits, follow the same behavior.
Local actions such as Enter still scroll the active row into view.

To verify this in Storybook, open a long notebook, place the caret near the top, and scroll down.
Apply a remote edit to the opening paragraph.
The content should update while the visible section stays in place.
