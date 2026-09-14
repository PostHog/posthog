# Session subscriptions

Command-center tiles select status fields for their own tasks through the task-to-run index.
Their view models do not keep transcript arrays alive.
PR badges and the chat footer select the output or timing fields they display.

Command-center tiles fold the latest stop reason incrementally, so a streaming background run costs one pass over the appended batch rather than a reverse scan of the transcript.

Cloud file summaries share an incremental tool-call tracker.
Text-only appends keep the same summary identity, and tool changes produce a new snapshot without mutating a previous result.
The tracker rebuilds when a transcript is replaced, including a same-length log reconcile that swaps a hydrated middle in while keeping the prefix and live tail.
The cache uses weak event keys so evicting a transcript can release its derived data.
Inactive review panes ignore session updates and skip tool-summary work.

Verification:

- Append text to a displayed task and another task; status-only views must not render again.
- Change permissions, completion, or run identity; the displayed status must update.
- Mount two file-summary consumers and verify that they share results, including after tool updates, history replacement, a same-length reconcile, and eviction.
