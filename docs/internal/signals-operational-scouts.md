# Operational scouts

A canonical scout declares `scout-role: operational` in its `SKILL.md` frontmatter.
The harness enables it outside the seed allowlist and the enabled-scout limit.
The holdback list still applies.
An operational scout remains exempt from inactivity warnings and pauses.
User pauses and failure pauses remain in effect.

The config records whether the role set `auto_pause_exempt` in `auto_pause_exempt_by_role`.
When a scout loses its operational role, the next coordinator tick removes only the exemption set by the role.
An explicit `auto_pause_exempt` edit through the config API clears this ownership marker, so the user setting survives a role change.
Role reconciliation runs independently of skill content hashes.

Archived canonical skills retain their operational identity in config responses.
The config API refuses to delete their configs.
Set `enabled=false` to stop an operational scout.

## Write eligibility

Operational scouts use the same write gates as other scouts.
Read `summary.emit_eligibility` from `scout-project-profile-get` to check the calling scout's write eligibility.
Use `summary_only=true` to omit the full inventory.
The response includes the calling scout's dry-run setting, but the cached profile keeps only the team-wide gates.
Outside a scout run, supply `run_id` to check a specific run on the project.

When `blocking_reason` is `scout_emit_disabled`, continue the investigation without emitting findings or reports.
Keep the findings in the run summary so a person can evaluate the dry run.
For a team-wide block, refresh the profile once with `force_refresh=true` before stopping the investigation.
If the block remains, record its reason and remediation in the run summary.
The write path checks eligibility again, so a successful profile check does not guarantee a later write.

## Roster sorting

The Scouts roster supports Name, Status, Recently created, Recently updated, and Last run.
The time-based options show the newest timestamp first, place missing timestamps last, and use alphabetical order for ties.
Recently updated uses the config `updated_at`, including system status changes.
Last run uses the last scheduled dispatch timestamp, not the completion time.
Manual and workflow-triggered runs do not update this timestamp.
