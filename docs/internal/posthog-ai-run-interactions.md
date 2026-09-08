# PostHog AI run interactions

The composer keeps typing local and debounces updates to the form state. Submission commits any pending draft before sending, so an immediate form reset clears the visible text. A submission that leaves the form unchanged preserves the draft.

The main chat keeps keyboard focus when a user clicks transcript text, even inside a focusable application panel. Escape can then stop the active run. The sidebar only handles Escape from its composer or approval controls.

Leaving the main task composer releases its pending creation and startup cancellation state. A late creation response must not navigate back to that task. Embedded composers keep their run when the main application navigates elsewhere.
