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
