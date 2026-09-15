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
server rejects the pause. The report stays archived. Only an explicit restore
request, without a pause interval or dismissal feedback, can restore it.

Dismissal updates the report immediately. A success message appears after the
server confirms the change. If the request fails, the previous report state is
restored and an error message appears.
