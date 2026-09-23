# Inbox report states

The report banner distinguishes a waiting report from an active investigation:

| State | Banner | Investigation spinner |
| --- | --- | --- |
| `potential` | Waiting for new signals | No |
| `potential` with dismissal reason `already_fixed` | Dismissed until new signals | No |
| `candidate` | Waiting to investigate | No |
| `in_progress` | Agent investigating | Yes |

Choosing **Already fixed** in the Dismiss dialog pauses the report. It returns to
`potential` and can return to the inbox when new matching signals arrive. This
action does not start an investigation. Other dismissal reasons archive the
report with status `suppressed`.

**Already fixed** is available for `in_progress`, `pending_input`, `ready`, and
`failed` reports. It is disabled for `potential` and `candidate` reports. These
reports can still be archived with another dismissal reason.

A `candidate` report does not always have a queued investigation. It can also
be waiting after a quota limit or unavailable signal data stops a run.

If another action archives the report before the pause request completes, the
server rejects the pause. The report stays archived. Restore requests can include
feedback notes. Requests with a pause interval or the `already_fixed` reason
cannot restore an archived report.

Dismissal updates the report immediately. A success message appears after the
server confirms the change. If the request fails, the previous report state is
restored and an error message appears.

## Relevance pilot

With `signals-relevance-pilot` enabled, the Reports inbox opens a personal shortlist of up to five reports. The backend selects P0–P2 reports suggested to the caller that need a decision or have a known-open PR ready for review, ordered by priority then recency. Each card gives its selection reason and links to the existing report detail to investigate, answer a question, or review the PR. **Browse all reports** opens the wider queue with the project scope.

**Not now** hides a report from only the caller's shortlist for seven days; **Undo** restores its eligibility. This is separate from the existing shared snooze that asks the pipeline to reconsider a report. It changes neither shared report state nor reviewers. The pilot reuses the ordinary report list and adds a personal snooze API, so deploy the backend before enabling the Desktop flag. Leave the flag off until then. Existing impression and report-action analytics distinguish this surface with `for_you_pilot` and `shortlist`; completion and qualitative usefulness matter more than clicks.
