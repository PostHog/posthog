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
The following controls apply:

- The token is scoped to the scout's project, so the organization-level copy endpoint is refused.
- The permissions of the person the scout acts as still apply per flag.
- A scout must disable an active flag and wait for any required approval before it can delete that flag. This applies to single and bulk deletes. A combined disable-and-delete request is refused while the flag is active.
- Changes to a flag appear in its activity log. Creating, editing, or deleting a scheduled change does not create a flag activity entry. Only a flag change that the schedule applies is logged.

The flag definition includes the IDs and names of linked, unarchived product tours in `product_tours`.

The run prompt tells a scout holding this grant to read a flag's whole definition first, check what the flag is linked to, prefer disable or archive over delete, and report what each change does to what users see.
It also requires a complete check of scheduled changes before any mutation. A scout leaves the flag unchanged if a pending or recurring schedule can still run, or if it cannot check schedules.
That is guidance to the run, not an API rule.

The shipped Feature flags scout can perform a final archive after explicit human approval and verified cleanup across deployed consumers. The write grant alone does not approve archival.

The grant is not restricted to hygiene writes, unlike `replay_scanner:write` in `products/replay_vision/backend/scout_writes.py`.
[#101988](https://github.com/PostHog/posthog/issues/101988) settled on granting the scope whole and stating the reach on every surface that offers it.

These notes describe scout sandbox tokens.
Session users, personal API keys, and ordinary OAuth tokens are unaffected by the grant.
