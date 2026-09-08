# Account property editors

Percent editors show percentage units, so a stored `0.184` appears as `18.4%`.
Saving converts the entered percentage back to its stored fraction.

Date-only properties preserve the calendar date from the API, including when the API
returns a UTC-midnight timestamp. Datetime properties retain local timezone handling.
The date picker keeps an attempted selection available after a failed save.
