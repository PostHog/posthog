# Outbound egress: rate limiting, observability, transport

Read the README before changing metrics, limiter keys, or adding an egress domain here.
Read a domain's own `README.md` before changing that domain, and invoke `/routing-outbound-api-calls` before adding or changing a domain.
Two things are easy to re-derive wrong: the identity model (key on the external budget owner, for example the GitHub App installation id, and **never** a PostHog DB row id) and GitHub's deliberate PAT scope decision in `github/README.md`.
A change to a domain's identity, budget, lanes, callers, or headers updates that domain's `README.md` in the same PR.
A TypeSafe caller meets "Usage policy" in `typesafe/README.md` before it merges: a staff-only feature flag, no customer data, and explicit opt-in plus leadership sign-off before launch.

@README.md
