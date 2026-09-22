# Scout write access for Replay vision scanners

A person can grant **Replay vision scanners** in a scout's write access settings.
The `replay_scanner:write` scope applies across the project from the next run.
Dry runs do not receive the grant.

A scout can create and update scanners, disable them, and use prompt suggestions based on human ratings.
Shared ratings must record explicit user verdicts. The scout must keep its own assessments in memory or reports.

Scout sandbox tokens have these API restrictions:

- A scanner must have a credit limit when the scout creates, copies, or enables it.
- A scout cannot remove a credit limit.
- New or increased scanner credit limits cannot exceed the organization's Replay vision credit quota.
- A finite organization quota is required for creation, copies, enabling, limit increases, and changes that can increase spend.
- Reducing a limit and disabling a scanner remain available without a finite organization quota.
- An enabled scanner must have a limit before the scout changes targeting, sampling, or the model.
- Prompt fixes and disabling remain available for existing scanners without a limit.
- Scouts cannot start inline scans, manual scans, prompt tests, retries, or historical backfills.
- Scouts cannot delete scanners. Disable a scanner to stop it and keep its observations.

These restrictions apply only to scout sandbox tokens.
Session users, personal API keys, and ordinary OAuth tokens retain their existing access rules.
