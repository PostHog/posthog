"""API scopes: what exists, who can grant and see each scope, and how OAuth names and limits them.

- `catalog`: every scope object and action, and the marker scopes PostHog's own code mints.
- `exposure`: the internal, hidden, privileged, grantable and resource sets.
- `oauth`: which scopes each OAuth surface lists, with a table of scope classes and surfaces.
- `checks`: whether held scopes cover required ones.
- `ceilings`: an OAuth app's scope ceiling and how a request resolves against it.
- `project_secret_api_key`: the scopes a project secret API key may carry.

Every module imports only the standard library and its siblings, through relative imports, so
`posthog/scopes_projection.py` can load the package without Django.
"""
