# Account property editors

Percent editors show percentage units, so a stored `0.184` appears as `18.4%`.
Saving converts the entered percentage back to its stored fraction.

Date-only properties preserve the calendar date from the API, including when the API
returns a UTC-midnight timestamp. Datetime properties retain local timezone handling.
The date picker keeps an attempted selection available after a failed save.

## Pin preferences

Omitting `pinned_properties` from a PATCH to
`/api/projects/:team_id/user_customer_analytics_config/@me/` preserves the existing
selection. An explicit empty list clears it.

API keys and OAuth tokens require `account:write` to change pins. Session-authenticated
viewers can personalize their own sidebar without permission to edit account values.

A failed save keeps the pin selector open with the attempted selection and order.
The user can retry the save or remove a rejected property.

Legacy child-environment URLs read and update the same user configuration as their parent project.
They require access to the parent project and its Customer analytics resource. Scoped
credentials must include the parent project, not only the child environment.
Successful pin saves emit `customer analytics account pinned properties saved` with aggregate
counts only. Failed attempts do not emit a success event.
