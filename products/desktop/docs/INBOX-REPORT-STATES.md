# Inbox report states

The report banner distinguishes a waiting report from an active investigation:

| State                                             | Banner                      | Investigation spinner |
| ------------------------------------------------- | --------------------------- | --------------------- |
| `potential`                                       | Waiting for new signals     | No                    |
| `potential` with dismissal reason `already_fixed` | Dismissed until new signals | No                    |
| `candidate`                                       | Waiting to investigate      | No                    |
| `in_progress`                                     | Agent investigating         | Yes                   |

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

## Personal ownership and shared scopes

With `signals-current-ownership` enabled, report details and Inbox settings expose
ownership controls. **Not me** removes your suggestion and saves a report-level
exclusion. It leaves the report state and work you already claimed unchanged.

A domain exclusion starts with a preview of affected reports. Confirming saves
the rule for future suggestions and cleans up existing suggestions. The preview
shows claimed work that cleanup will preserve. Undo restores only removals from
that operation that have not changed since; later edits and rules take priority.

Team, product-domain, and unclassified scopes keep reports discoverable after
personal exclusions. Shared domain/team corrections are separate from private
preferences. Deploy the ownership API before enabling these Desktop controls.
