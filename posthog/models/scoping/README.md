# Team Scoping Module

Automatic team scoping for Django models to prevent IDOR vulnerabilities.

## Overview

This module provides infrastructure for automatically filtering database queries by the current team. Instead of relying on developers to always include `team_id` filters, models can use `TeamScopedManager` to automatically apply the filter based on request context.

## Quick Start

### For Request Handlers (Views, API Endpoints)

The middleware automatically sets the team context from `request.user.current_team_id`. Models using `TeamScopedManager` will automatically filter queries.

```python
# In a view or API endpoint - team scoping is automatic
flags = FeatureFlag.objects.all()  # Only returns flags for current user's team
```

### For Background Jobs (Celery Tasks)

Background tasks don't have request context. Use the `@with_team_scope` decorator:

```python
from celery import shared_task
from posthog.models.scoping import with_team_scope

@shared_task
@with_team_scope()
def process_team_data(team_id: int, data: dict):
    # Team context is set from the team_id parameter
    flags = FeatureFlag.objects.all()  # Filtered to team_id
```

Or use the `team_scope()` context manager directly:

```python
from posthog.models.scoping import team_scope

@shared_task
def process_team_data(team_id: int, data: dict):
    with team_scope(team_id):
        flags = FeatureFlag.objects.all()
```

### For Cross-Team Queries

When you intentionally need to query across teams (e.g., admin dashboards, analytics), use `.unscoped()`:

```python
# Query all teams explicitly
all_flags = FeatureFlag.objects.unscoped().filter(key="my-global-flag")
```

Or use the `unscoped()` context manager:

```python
from posthog.models.scoping import unscoped

with unscoped():
    all_flags = FeatureFlag.objects.all()  # All teams
```

## Migrating a Model

### Step 1: Switch to BackwardsCompatibleTeamScopedManager

This maintains compatibility with existing `filter(team_id=X)` patterns:

```python
from posthog.models.scoping.manager import BackwardsCompatibleTeamScopedManager

class MyModel(models.Model):
    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    # ... other fields ...

    objects = BackwardsCompatibleTeamScopedManager()
```

### Step 2: Update Celery Tasks

Add `@with_team_scope` decorator or use `.unscoped()`:

```python
# Before
@shared_task
def my_task(team_id: int):
    MyModel.objects.filter(team_id=team_id).all()

# After (option 1: decorator)
@shared_task
@with_team_scope()
def my_task(team_id: int):
    MyModel.objects.all()  # Automatically filtered

# After (option 2: unscoped for cross-team)
@shared_task
def my_task():
    MyModel.objects.unscoped().all()  # Explicitly cross-team
```

### Step 3: Update Cross-Team Queries

Find places that intentionally query across teams and add `.unscoped()`:

```python
# Before
MyModel.objects.filter(key="global-setting")  # Was relying on no team filter

# After
MyModel.objects.unscoped().filter(key="global-setting")  # Explicitly cross-team
```

### Step 4: Switch to TeamScopedManager (Optional)

Once all `filter(team_id=X)` usages are removed, switch to strict scoping:

```python
from posthog.models.scoping.manager import TeamScopedManager

class MyModel(models.Model):
    objects = TeamScopedManager()
```

## API Reference

### Context Functions

- `get_current_team_id()` - Returns the current team_id or None
- `set_current_team_id(team_id)` - Sets team_id, returns reset token
- `reset_current_team_id(token)` - Resets to previous value

### Context Managers

- `team_scope(team_id)` - Sets team context for a block
- `unscoped()` - Clears team context for a block

### Decorators

- `@with_team_scope(team_id_param="team_id")` - Wraps function in team context

### Managers

- `TeamScopedManager` - Strict automatic scoping
- `BackwardsCompatibleTeamScopedManager` - Also supports `filter(team_id=X)`

### Middleware

- `TeamScopingMiddleware` - Sets team context from request.user

## Semgrep Rules

The `celery-task-team-scope-audit` rule flags Celery tasks that access models without explicit team scoping. Run with:

```bash
semgrep --config .semgrep/rules/celery-team-scope.yaml .
```
