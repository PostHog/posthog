# GitHub domain helpers

Code about GitHub that more than one product needs and that is neither transport nor an outbound call.
Inbound transport is `posthog/ingress/github/`, outbound calls are `posthog/egress/github/`, and neither imports the other.
Both may import this package.

- `installations.py` reads the installation id off a payload and resolves the teams linked to it.
- `attribution.py` resolves a GitHub login to an organization member, under a bounded statement timeout, so a slow lookup degrades to no attribution.
- `pull_request_events.py` emits the canonical `pr_created`, `pr_closed`, `pr_merged` and `pr_reviewed` analytics events.
- `metrics.py` holds the Prometheus counters for dropped events and attribution outcomes.

## PR analytics

A consumer that owns a pull request builds a `PullRequestAttribution` and passes it to `capture_pr_event`.
The caller owns PR matching, team authorization and product side effects; the emitter owns actor resolution and the common PR properties.

- Canonical PR properties, `team_id` and `pr_source` take precedence over the caller's properties.
- The caller's default actor stays when the GitHub user cannot be resolved.
- PR title, body, labels, reviewers and draft status are sent only when the attribution sets `include_content`.
- With no attribution, the event goes to the first team linked to the installation, in team-id order, without content.
- Event UUIDs derive from the PR URL and the event name, plus the review id for reviews, so a redelivery reuses the UUID and a close/reopen cycle keeps one `pr_closed`.
- Capture is best effort: a failure increments the dropped-event counter and never blocks the caller.
