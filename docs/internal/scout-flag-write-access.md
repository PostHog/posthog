# Scout write access for feature flags

A person can grant **Feature flags** in a scout's write access settings.
The `feature_flag:write` scope applies across the project from the next run.
Dry runs do not receive the grant.

This grant is different in kind from the others in the picker.
Every other one writes an artifact: a dashboard, an insight, a warehouse view.
A feature flag decides what end users see, so a granted scout can change production behavior.

A scout can create, update, enable, disable, archive, and delete flags, manage their scheduled changes, and use the bulk delete endpoint.
The reach is every flag in the project.
It is not limited to stale flags, and not limited to flags the scout created.
That includes the flags an experiment, an early access feature, a survey, a product tour, or a session replay setting runs on, so a change can stop those products too.

Grant it to one scout whose skill body names the flags it maintains, and read that skill body first.
Nothing in the API narrows the grant further than the scope does.
Two things bound it, both of which already applied to every scout:

- The token is scoped to the scout's project, so the organization-level copy endpoint is refused.
- The permissions of the person the scout acts as still apply per flag, and every write lands in the flag's activity log.

The run prompt tells a scout holding this grant to read a flag's whole definition first, check what the flag is linked to, prefer disable or archive over delete, and report what each change does to what users see.
That is guidance to the run, not an API rule.

Restricting the grant to hygiene writes, the way `replay_scanner:write` is restricted in `products/replay_vision/backend/scout_writes.py`, is a decision the team has not taken.
[#101988](https://github.com/PostHog/posthog/issues/101988) settled on granting the scope whole and stating the reach on every surface that offers it.

These notes describe scout sandbox tokens.
Session users, personal API keys, and ordinary OAuth tokens are unaffected by the grant.
