# Outbound rate limiting & egress observability

Read the README before changing metrics, limiter keys, or adding an egress domain here.
Two things are easy to re-derive wrong: the identity model (key on the external budget owner — e.g. the GitHub App installation id — **never** a PostHog DB row id) and the deliberate PAT scope decision.

@README.md
