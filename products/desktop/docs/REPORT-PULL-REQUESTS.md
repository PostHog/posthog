# Report pull requests

Desktop, web-host, and mobile inbox surfaces read the report's `pull_requests` collection through the shared report PR helpers.
The collection includes artefact links and legacy task-output PRs supplied by the backend.
When a server omits the collection, the helpers fall back to `implementation_pr_url`, `implementation_pr_state`, and `implementation_pr_merged`.
An explicitly empty collection takes precedence over legacy fields.

The primary PR is deterministic: unfinished PRs first, then merged, then closed, with URL ordering for ties.
The desktop report detail selector lets a reviewer choose another PR.
GitHub links, checks, files, and comments follow that selection; switching PRs resets review-panel state.

Task continuation uses PR attachment attribution to identify the internal task, including automatically created `agent_run` associations.
Agent prompts use the claim, attach PRs, and release workflow and carry the returned claim ID.
Claim display names are not displayed by this change.

This client update depends on the report claims and PR API in PostHog/posthog#97846.
Deploy that backend before releasing the desktop update.
