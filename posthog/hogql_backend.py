from importlib import import_module
from typing import Any

from common.hogql.hooks import HogQLBackendHooks, set_hogql_backend_hooks


class PostHogHogQLBackendHooks(HogQLBackendHooks):
    def resolve_symbol(self, module: str, name: str) -> Any:
        return getattr(import_module(module), name)

    def create_notice(
        self,
        *,
        start: int | None,
        end: int | None,
        message: str,
        fix: str | None,
    ) -> Any:
        from posthog.schema import HogQLNotice  # noqa: PLC0415 - keeps schema imports behind hook calls

        return HogQLNotice(start=start, end=end, message=message, fix=fix)

    def create_query_timing(self, *, kind: str, duration_seconds: float) -> Any:
        from posthog.schema import QueryTiming  # noqa: PLC0415 - keeps schema imports behind hook calls

        return QueryTiming(k=kind, t=duration_seconds)

    def create_default_query_modifiers(self) -> Any:
        from posthog.schema import HogQLQueryModifiers  # noqa: PLC0415 - keeps schema imports behind hook calls

        return HogQLQueryModifiers()

    def get_project_id_for_team(self, team_id: int) -> int:
        from posthog.models import Team  # noqa: PLC0415 - avoids importing Django models from the adapter module

        return Team.objects.only("project_id").get(id=team_id).project_id


def install_hogql_backend_hooks() -> None:
    set_hogql_backend_hooks(PostHogHogQLBackendHooks())
