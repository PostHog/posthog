"""Module-import-safe marker for the celery-task-team-scope-audit semgrep rule.

Lives at the top of the `posthog` package (not under `posthog.models`)
because Celery task modules import this at module load — and importing
from `posthog.models.*` at that point triggers `posthog.models.__init__`
to load every model in the codebase, which fails before Django's app
registry is ready (e.g. during `posthog.apps.py` initialization for
modules pulled in by the celery app config).

The framework's other scoping helpers (TeamScopedManager,
ProductTeamModel, team_scope, etc.) live in `posthog.models.scoping`
because they're inherently model-tied and only get imported once Django
apps are loaded.
"""

from collections.abc import Callable
from typing import ParamSpec, TypeVar

P = ParamSpec("P")
R = TypeVar("R")


def skip_team_scope_audit(func: Callable[P, R]) -> Callable[P, R]:
    """No-op marker that silences the celery-task-team-scope-audit semgrep rule.

    Apply this to Celery tasks that query models which don't read the
    scoping ContextVar — i.e. anything still on `RootTeamManager` or the
    default Django manager. Those tasks don't need `@with_team_scope`
    because the model's manager isn't fail-closed; the auto-rewrite on
    save (`RootTeamMixin.save()`) handles the canonical-id concern.

    The decorator does nothing at runtime. Its only purpose is to make
    "this task is intentionally exempt" explicit and reviewable, in
    contrast to `# nosemgrep` comments which carry no semantic content.

    Remove it once the underlying model migrates to `TeamScopedManager` —
    after which the task will need `@with_team_scope` or `.unscoped()`.

    Example:
        @shared_task
        @skip_team_scope_audit  # FeatureFlag still uses RootTeamManager
        def my_task():
            FeatureFlag.objects.filter(...).delete()
    """
    return func


__all__ = ["skip_team_scope_audit"]
