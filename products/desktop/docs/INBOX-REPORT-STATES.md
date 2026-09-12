# Inbox report states

The report banner distinguishes a waiting report from an active investigation:

| State | Banner | Investigation spinner |
| --- | --- | --- |
| `potential` | Waiting for new signals | No |
| `potential` with dismissal reason `already_fixed` | Dismissed until new signals | No |
| `candidate` | Queued for investigation | No |
| `in_progress` | Agent investigating | Yes |

Choosing **Already fixed** in the Dismiss dialog pauses the report. It returns to
`potential` and can return to the inbox when new matching signals arrive. This
action does not start an investigation. Other dismissal reasons archive the
report with status `suppressed`.

Dismissal updates the report immediately. A success message appears after the
server confirms the change. If the request fails, the previous report state is
restored and an error message appears.
