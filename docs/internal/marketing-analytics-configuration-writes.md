# Marketing configuration writes

Settings updates send only the changed field and refresh the Marketing configuration under a row lock, preserving unrelated concurrent changes.

Explicit conversion-goal list updates still replace the list; simultaneous edits to that same list are not merged.

Loading a project replaces the current and saved Marketing settings with that project’s configuration, including an empty configuration when none exists.

Setup usage emits `marketing analytics setup section viewed` on entry and section changes.
Suggestion review, dismissal, restoration, batch review, capability filters, rescans and navigation have separate events.
`marketing analytics setup change submitted`, `change completed` and `change failed` share the same prefix and report operation types, counts, source and whether the change is an undo. Completed reports the server's applied count, which may be zero.
`marketing analytics setup sync retry completed` reports requested and failed counts; it measures scheduling retries, not completed syncs.
Payloads exclude suggestion IDs, titles, evidence, goal names and UTM values. Source navigation measures entry into connection flows; existing warehouse connection events measure their completion.
