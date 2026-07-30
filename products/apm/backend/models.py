"""
Django models for apm.

Keep models thin — business logic belongs in logic/.
Use types from facade/enums.py where applicable.
Avoid ForeignKeys to models outside this app; if needed,
disallow reverse relations with related_name='+'.

Models must inherit TeamScopedRootMixin to opt into fail-closed team
scoping — queries without team context raise TeamScopeError instead of
silently returning every team's rows. Main-DB products add
`team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)`.
See posthog/models/scoping/README.md.
"""
