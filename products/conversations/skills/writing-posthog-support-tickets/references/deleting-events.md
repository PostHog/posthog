# Deleting events

Deleting events cannot be undone, and support runs a deletion only when there is no self-serve route.
A ticket with everything below lets support start the request the day they read it.
A ticket without it gets a reply asking for each missing item.

## Check the self-serve routes first

Tell the person when one of these fits, and write no ticket unless they still need one:

- **Erasing a known person.** They can delete the person together with their events, which removes all of that person's events. It does not fit when some of the person's other events must stay.
- **Deleting recordings.** They can delete recordings themselves.
- **Deleting events by age.** On a paid plan, they can shorten [events retention](https://posthog.com/docs/data/events-retention) in their settings. It fits only when every event older than a date should go. The free plan keeps events for a fixed 1 year. [Recording retention](https://posthog.com/docs/session-replay/recording-retention) is a separate setting, and it applies only to new recordings.
- **Removing a property and keeping the events.** Support cannot usually do this. Tell the person before you write anything, unless they already said that deleting the events is fine. If they still want to ask, write the ticket as a request to delete those events, with everything below, and say in **Left for support** that they would rather keep the events if PostHog can remove only the properties.

Do not offer other workarounds from memory. Check them with `posthog:docs-search` first.

## What the ticket must include

**Region and project ID.**
Take the ID from `posthog:project-get` and the region from the host of a `_posthogUrl`.
IDs repeat across regions, so always give both.
A query covers one project, so give a query and a count for each project.

**One query that selects exactly the events to delete.**
Write it in HogQL against `events`:

- Pin both time bounds to UTC, such as `timestamp >= toDateTime('2026-10-01 00:00:00', 'UTC')`. A bound without a timezone is read in the project's timezone, so copying it unconverted deletes a different set of events.
- End with a fixed time in the past, using `<`. Never use `now()`, because the deletion runs days later.
- When the person gives no start, start at the day of the project's first event, and say so. When a bound they give is approximate, ask them for the exact time. Do not pick one for them.
- Name the events with `event = '...'` or `event IN (...)`. If every event in the window should go, leave out the event condition and say so.
- Filter on the property that identifies the scope, such as `properties.$host` for one web app.
- Keep to conditions on `events`. `JOIN`, `LIMIT` and `HAVING` do not map onto the deletion request.
- `!=`, `NOT` and `NOT IN` also match events where the property is missing. Check that the person wants that.

**The count that query returned.**
Run it as `SELECT count() FROM events WHERE <the same conditions>` with `posthog:execute-sql`.
Support checks the deletion against this number and stops if they differ.

**The person's confirmation.**
Show the person the query and the count before you write the ticket, and ask them to confirm that this is exactly what to delete.
Then **Left for support** asks to delete that many events, such as "Delete the 3,817 events this query returns".
A ticket that gives the query and its count and asks for the deletion counts as their confirmation, so support does not ask again.

When you hand it over, tell the person to send it from their own PostHog account, through the draft tool or the Support panel, and not from another email address.
Support checks that the requester is a member of the organization that owns the project.

## Leave out

- How the data got there, beyond one sentence in **Request**. Support needs the scope, not the history.
- Asking support to keep the persons. Deleting events leaves persons in place.
- Volume estimates for other event types, and properties outside the scope.
- Anything about other projects, unless each one has its own query and count.

## Example

````text
Request: Please delete the test checkout events that our staging build sent to our live project in the first week of October 2026.

Details:
- Project: Web app, ID 12345, US Cloud, https://us.posthog.com/project/12345
- Events: `checkout_started` and `checkout_completed` from the host `staging.example.com`
- Query, which returned 3,817 events:

```sql
SELECT count()
FROM events
WHERE timestamp >= toDateTime('2026-10-01 00:00:00', 'UTC')
  AND timestamp < toDateTime('2026-10-08 00:00:00', 'UTC')
  AND event IN ('checkout_started', 'checkout_completed')
  AND properties.$host = 'staging.example.com'
```

Already checked:
- Claude Code checked: no self-serve route fits, because the same persons have real events that must stay
- Claude Code checked: the query returns 3,817 events, all from `staging.example.com`

Left for support: Delete the 3,817 events this query returns.
````
