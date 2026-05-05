# Team Scoping

Fail-closed team scoping for Django models. Queries without team context raise `TeamScopeError` instead of silently returning all rows.

This is a defense-in-depth convenience layer, not a complete security boundary. Django's `_base_manager` bypasses custom managers for related-object access, and raw SQL bypasses the ORM entirely. Use this alongside explicit team checks at the API layer.

Related: [#47073](https://github.com/PostHog/posthog/pull/47073)

## How it works

A ContextVar holds the current team_id. The scoped manager reads it and auto-filters. No context = exception. Context is set by:

- **DRF nested views** — `TeamAndOrgViewSetMixin.initial()` sets it from the URL team_id (the team being acted on, not the user's "current" team — see #50899 for the equivalent org bug).
- **Celery tasks / management commands / anything else** — explicitly via `team_scope()` or `@with_team_scope()`.

There is intentionally no middleware fallback that defaults to `user.current_team_id`. That value is a UI preference and can drift from the team being acted on; using it as a silent default is exactly the bug class this framework is meant to prevent.

```python
# DRF view — context set automatically by TeamAndOrgViewSetMixin from URL
Repo.objects.all()                    # filtered to URL team_id

# no context — raises TeamScopeError
Repo.objects.all()                    # ← boom

# explicit cross-team (opt-out)
Repo.objects.unscoped().all()         # no filtering, no error

# explicit team (outside request)
Repo.objects.for_team(team_id)        # filtered to team_id

# background jobs
with team_scope(team_id):
    Repo.objects.all()                # filtered to team_id

# celery tasks
@shared_task
@with_team_scope()
def my_task(team_id: int): ...        # context set from param
```

## Which manager to use

| Situation                  | Manager                            | Why                                            |
| -------------------------- | ---------------------------------- | ---------------------------------------------- |
| New product on separate DB | `ProductTeamModel` (abstract base) | No FK to Team, plain `team_id` field, no JOINs |
| Migrating existing model   | `TeamScopedManager`                | Same fail-closed behavior, uses FK JOINs       |

## ProductTeamModel (for multi-DB products)

```python
from posthog.models.scoping.product_mixin import ProductTeamModel

class Repo(ProductTeamModel):
    repo_name = models.CharField(max_length=255)
    # team_id inherited — BigIntegerField, no FK
```

Auto-scoped queries, `.unscoped()` escape hatch, `.for_team(id)` for explicit scoping.

## Known limitations

- **`_base_manager`**: Django uses `_base_manager` (not `objects`) for related-object access like `repo.runs.all()`. This bypasses the scoped manager. Related-object traversal is still safe because the FK constrains the result set — but the team_id filter is not applied.
- **Raw SQL**: `cursor.execute()` and `QuerySet.raw()` bypass managers entirely.
- **Django admin**: Uses `_default_manager`. Since `objects` is declared first on `ProductTeamModel`, admin goes through the scoped manager and will raise without context. Use `.unscoped` in admin classes.
