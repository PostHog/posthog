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
