# Team Scoping

Fail-closed team scoping for Django models. Queries without team context raise `TeamScopeError` instead of silently returning all rows.

This is a defense-in-depth convenience layer, not a complete security boundary. Django's `_base_manager` bypasses custom managers for related-object access, and raw SQL bypasses the ORM entirely. Use this alongside explicit team checks at the API layer.

Related: [#47073](https://github.com/PostHog/posthog/pull/47073), [#50899](https://github.com/PostHog/posthog/pull/50899)

## The contract

A ContextVar holds the **canonical** team_id — the parent team's id when the team is a child environment, the team's own id otherwise. Reads filter by it. Writes through `ProductTeamModel.save()` rewrite child team_ids to canonical (mirror of `RootTeamMixin.save()` for main-DB models). No context = exception.

`team_scope()` / `with_team_scope()` / `for_team()` auto-resolve to canonical by default — one Team lookup per scope entry, much cheaper than per-query resolution and removes the silent-zero-rows footgun where `with team_scope(child_id):` would scope reads to a child id with no data. Pass `canonical=True` to skip resolution when the caller already has the canonical id (or in tests with synthetic ids).

## Where context gets set

- **DRF nested views** — `TeamAndOrgViewSetMixin.initial()` sets it from the URL `self.team_id` (the team being acted on, not the user's "current" team). Reuses `self.team.parent_team_id` if cached by permission checks for free.
- **Celery tasks** — `@with_team_scope()` decorator extracts a `team_id` parameter from the task signature.
- **Management commands / ad-hoc scripts** — `with team_scope(team_id):` block.

There is no middleware fallback. The original POC (#46874) had one defaulting to `user.current_team_id`, but that value is a UI preference and can drift from the team being acted on — using it as a silent default is exactly the bug class this framework is meant to prevent. Non-DRF code paths must opt in.

## Usage

```python
# DRF view — context set automatically from the URL
Repo.objects.all()                       # filtered to canonical team

# no context — raises TeamScopeError
Repo.objects.all()                       # ← boom

# explicit cross-team escape hatch (queryset method)
Repo.objects.unscoped().all()            # no filtering, no error

# explicit scope to one team (auto-resolves to canonical)
Repo.objects.for_team(team_id)

# bulk over many teams — pre-resolve once, skip per-call lookup
canonical_ids = [resolve_effective_team_id(t.id) for t in teams]
for cid in canonical_ids:
    Repo.objects.for_team(cid, canonical=True).count()

# background scope block (auto-resolves)
with team_scope(team_id):
    Repo.objects.all()

# celery task — same auto-resolve, applied via decorator
from celery import shared_task
from posthog.models.scoping import with_team_scope

@shared_task
@with_team_scope()
def my_task(team_id: int):
    Repo.objects.all()
```

## Adoption

### New product on a separate database

Use `ProductTeamModel` as the abstract base. It declares `team_id` as a `BigIntegerField` (no FK, since cross-DB FKs aren't supported), wires `objects = TeamScopedManager()`, and overrides `save()` to rewrite to canonical.

```python
from posthog.models.scoping.product_mixin import ProductTeamModel

class Repo(ProductTeamModel):
    repo_name = models.CharField(max_length=255)
    # team_id inherited — BigIntegerField, indexed, no FK
```

### Existing main-DB model

Keep your `RootTeamMixin` (it already declares `team` as `ForeignKey("Team", ...)` and rewrites on save). Swap the manager:

```python
class FeatureFlag(RootTeamMixin):                # unchanged — handles save() + FK
    objects = TeamScopedManager()                # was RootTeamManager() — adds enforcement
```

The manager is the same class for both worlds — `ProductTeamModel` and `RootTeamMixin` differ only in how `team_id` is stored (FK vs BigInt). Migrating any existing model means swapping its manager and auditing every call site to either be inside team scope or use `.unscoped()`.

### Celery tasks against models still on RootTeamManager

`RootTeamManager`-backed models don't read the ContextVar, so `@with_team_scope` adds nothing — but the semgrep rule `celery-task-team-scope-audit` flags any unscoped `Model.objects.X` in a Celery task. For tasks that legitimately don't need scope (model still on the older manager, or genuinely cross-team), tag the task with the no-op marker:

```python
from posthog.scoping_audit import skip_team_scope_audit

@shared_task
@skip_team_scope_audit  # FeatureFlag still uses RootTeamManager
def my_task():
    FeatureFlag.objects.filter(...).delete()
```

Remove the marker once the underlying model migrates to `TeamScopedManager`. The decorator lives at `posthog.scoping_audit` (not `posthog.models.scoping`) so it can be imported at module load by Celery task files without triggering Django's app registry — see the file's docstring for the load-order story.

## Bypass managers

Two surfaces to opt out of scoping, named distinctly to avoid an autocomplete trap:

- `Model.objects.unscoped()` — queryset method on the scoped manager. Returns a fresh `TeamScopedQuerySet` with no filter applied. Use this for "I want to query across teams in this one place" within normal request lifecycle code.
- `Model.all_teams` — second plain `Manager` declared on `ProductTeamModel`. Use this for code that runs _outside_ the request lifecycle (admin classes, migrations, manage.py commands) where setting context with `team_scope(...)` is awkward.

The two are deliberately not the same name. A future contributor autocompleting `Model.unscoped.filter(...)` thinking they're being explicit about scoping would otherwise silently get every team's rows back.

## Known limitations

- **`_base_manager`**: Django uses `_base_manager` (not `objects`) for related-object access like `repo.runs.all()`. This bypasses the scoped manager. Related-object traversal is still safe because the FK constrains the result set — but the `team_id` filter is not applied.
- **Raw SQL**: `cursor.execute()` and `QuerySet.raw()` bypass managers entirely.
- **Django admin**: Uses `_default_manager`. Since `objects` is declared first on `ProductTeamModel`, admin goes through the scoped manager and would raise without context — use `Model.all_teams` in admin classes.
