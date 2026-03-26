# Rate Limiter Refactoring Analysis

**File:** `posthog/clickhouse/client/limit.py`
**Date:** 2026-01-07

## Summary

The `limit.py` module provides Redis-based concurrency limiting for ClickHouse queries. Originally written for a single use case, it has evolved to support five different rate limiters with increasingly complex conditional logic. This document analyzes the current issues and proposes refactoring strategies.

---

## Current Architecture

### Core Components

1. **`RateLimit` dataclass** - Generic rate limiting with Redis sorted sets and Lua scripts
2. **Five factory functions** - Each returns a singleton rate limiter:
   - `get_api_team_rate_limiter()` - API queries per team (3 concurrent)
   - `get_app_org_rate_limiter()` - App queries per org (20 concurrent)
   - `get_app_dashboard_queries_rate_limiter()` - Dashboard queries per org (6 concurrent)
   - `get_web_analytics_api_rate_limiter()` - Web analytics per team (3 concurrent)
   - `get_materialized_endpoints_rate_limiter()` - Materialized endpoints per team (10 concurrent)
3. **`limit_concurrency` decorator** - For Celery tasks (separate implementation)

### Usage Locations

- **`query_runner.py`** - Main usage, stacks all 4 query limiters
- **`external_web_analytics/http.py`** - Uses web analytics limiter
- **`tasks.py`** - Uses `limit_concurrency` decorator on `process_query_task`

---

## Issues

### 1. Business Logic Hardcoded in `RateLimit.use()` (lines 108-112)

```python
in_beta = kwargs.get("is_api") and (team_id in settings.API_QUERIES_PER_TEAM)
if in_beta:
    max_concurrency = settings.API_QUERIES_PER_TEAM[team_id]
elif limit_value := kwargs.get("limit", None):
    max_concurrency = int(limit_value)
```

This API-specific beta logic doesn't belong in the generic `RateLimit` class. It couples the core class to a specific business requirement.

### 2. Duplication Between `RateLimit` and `limit_concurrency` Decorator

Both implement:
- Same Lua script for atomic operations
- Similar acquire/release patterns
- Similar metric tracking (`CONCURRENT_TASKS_LIMIT_EXCEEDED_COUNTER` vs `CONCURRENT_QUERY_LIMIT_EXCEEDED_COUNTER`)

The decorator (lines 357-396) could use `RateLimit` internally instead of duplicating ~40 lines of logic.

### 3. Repeated Patterns in Factory Functions

Each factory function has nearly identical structure:
- Global singleton variable
- `applicable` lambda with duplicated checks (`not TEST`, `not current_task`)
- `get_task_name` lambda following pattern `<prefix>:query:per-<scope>:<id>`
- `get_task_id` lambda with same celery/kwargs/generate fallback

### 4. Complex `applicable` Callbacks

Each limiter duplicates checks for:
- `not TEST` - Skip in test environment
- `not current_task` - Skip in Celery context
- `not _is_in_temporal()` - Skip in Temporal context (dashboard limiter only)

Example from `get_app_org_rate_limiter()`:
```python
applicable=lambda *args, **kwargs: (
    not TEST
    and kwargs.get("org_id")
    and not kwargs.get("is_api")
    and not current_task
),
```

### 5. Five Singleton Globals

```python
__API_CONCURRENT_QUERY_PER_TEAM: Optional[RateLimit] = None
__APP_CONCURRENT_QUERY_PER_ORG: Optional[RateLimit] = None
__APP_CONCURRENT_DASHBOARD_QUERIES_PER_ORG: Optional[RateLimit] = None
__WEB_ANALYTICS_API_CONCURRENT_QUERY_PER_TEAM: Optional[RateLimit] = None
__MATERIALIZED_ENDPOINTS_CONCURRENT_QUERY_PER_TEAM: Optional[RateLimit] = None
```

These could be consolidated into a registry pattern.

---

## Proposed Refactoring

### Change 1: Extract `max_concurrency` Resolution to a Callback

Add optional callback to dynamically resolve max_concurrency:

```python
@dataclasses.dataclass
class RateLimit:
    max_concurrency: int
    get_max_concurrency: Optional[Callable[..., int]] = None  # NEW

    def use(self, *args, **kwargs) -> tuple[Optional[str], Optional[str]]:
        max_concurrency = (
            self.get_max_concurrency(*args, **kwargs)
            if self.get_max_concurrency
            else self.max_concurrency
        )
        # ... rest without hardcoded beta logic
```

Move API-specific logic to factory:
```python
def _get_api_max_concurrency(*args, team_id=None, is_api=None, limit=None, **kwargs) -> int:
    if is_api and team_id in settings.API_QUERIES_PER_TEAM:
        return settings.API_QUERIES_PER_TEAM[team_id]
    if limit is not None:
        return int(limit)
    return 3
```

### Change 2: Create Composable Predicates for `applicable`

```python
def not_in_test() -> bool:
    return not TEST

def not_in_celery() -> bool:
    return not current_task

def not_in_temporal() -> bool:
    try:
        from temporalio import activity, workflow
        return not (workflow.in_workflow() or activity.in_activity())
    except ImportError:
        return True

def all_of(*predicates: Callable[..., bool]) -> Callable[..., bool]:
    """Compose multiple predicates with AND logic."""
    def combined(*args, **kwargs) -> bool:
        return all(p(*args, **kwargs) for p in predicates)
    return combined

def requires_kwarg(key: str) -> Callable[..., bool]:
    return lambda *args, **kwargs: bool(kwargs.get(key))

def excludes_kwarg(key: str) -> Callable[..., bool]:
    return lambda *args, **kwargs: not kwargs.get(key)
```

Usage becomes declarative:
```python
RateLimit(
    applicable=all_of(
        not_in_test,
        not_in_celery,
        requires_kwarg("org_id"),
        excludes_kwarg("is_api"),
    ),
    ...
)
```

### Change 3: Simplify Task Name/ID Generation

```python
def task_name_for_scope(prefix: str, scope: str, key: str) -> Callable[..., str]:
    """Generate task name like 'api:query:per-team:123'"""
    return lambda *args, **kwargs: f"{prefix}:query:per-{scope}:{kwargs.get(key)}"

def default_task_id(*args, **kwargs) -> str:
    """Get task ID from celery, kwargs, or generate one."""
    if current_task:
        return current_task.request.id
    return kwargs.get("task_id") or generate_short_id()
```

### Change 4: Unify `limit_concurrency` Decorator with `RateLimit`

```python
def limit_concurrency(
    max_concurrent_tasks: int,
    key: Optional[Callable] = None,
    ttl: int = 60 * 15,
    limit_name: str = ""
) -> Callable:
    def decorator(task_func):
        limiter = RateLimit(
            max_concurrency=max_concurrent_tasks,
            limit_name=limit_name,
            get_task_name=lambda *args, **kwargs: f"celery_running_tasks:{current_task.name}",
            get_task_key=(
                (lambda *args, **kwargs: f"celery_running_tasks:{current_task.name}:{key(*args, **kwargs)}")
                if key else None
            ),
            get_task_id=lambda *args, **kwargs: f"{current_task.name}:{current_task.request.id}",
            ttl=ttl,
            bypass_all=False,
        )
        return limiter.wrap(task_func)
    return decorator
```

### Change 5: Use Registry Pattern for Rate Limiters

```python
class RateLimiterRegistry:
    _limiters: dict[str, RateLimit] = {}

    @classmethod
    def get(cls, name: str, factory: Callable[[], RateLimit]) -> RateLimit:
        if name not in cls._limiters:
            cls._limiters[name] = factory()
        return cls._limiters[name]

    @classmethod
    def clear(cls):
        """For testing."""
        cls._limiters.clear()
```

---

## Implementation Order

1. Add `get_max_concurrency` callback to `RateLimit` (backward compatible)
2. Add composable predicate helpers
3. Add task name/id helper functions
4. Migrate factory functions to use new helpers (one at a time)
5. Refactor `limit_concurrency` to use `RateLimit`
6. (Optional) Add registry pattern
7. Remove hardcoded beta logic from `RateLimit.use()`

---

## Considerations

- **Backward compatibility**: All changes are backward compatible since factory functions are the public API
- **Testing**: Existing tests in `test_limit.py` should continue to pass
- **Incremental**: Can implement subset of changes if full refactor is too invasive
- **Metrics**: Ensure metric labels remain consistent during refactoring
