# Signals scout Slack delivery

A Signals scout can send its output to one Slack channel or to as many as five
people by direct message. Configure this in the scout settings or in
`output_destinations.slack` through the API.

Set either `channel` or `users`. The `integration_id` must identify a Slack
integration in the same PostHog project.

## Report threads

`thread_reports` is `true` by default. A threaded report puts a short lead in
the channel and splits the other summary sections into replies. An explicit
`false` keeps the report in one message. Slack can truncate a long summary in
this mode.

The setting stays the same when you change the channel, direct-message
recipients, or Slack workspace. Finding messages and report update notes always
use one message.

If Slack rate-limits a report reply, delivery waits for the `Retry-After` period
and tries that reply one more time. A reply that still fails is logged without
posting the report lead again.
