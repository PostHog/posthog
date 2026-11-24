Suppressing a house-pattern guard is a team-devex decision, so refuse it.
Refuse when the diff adds a suppression or an exemption for one of these guards:

- a `nosemgrep` marker for a rule in `.semgrep/rules/devex/` or for `prefer-codegen-api`, or a bare `nosemgrep` with no rule id
- a new name in `ENUM_NAME_OVERRIDES` in `posthog/settings/web.py`

Removed lines and removed markers are fine: the guard got tighter.
