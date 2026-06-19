from importlib import import_module
from typing import Any

from common.hogql.hooks import HogQLBackendHooks, set_hogql_backend_hooks
from common.hogql.parser_reporter import set_parser_exception_reporter


def _capture_parser_exception(exception: Exception, additional_properties: dict[str, Any] | None) -> None:
    from posthog.exceptions_capture import capture_exception  # noqa: PLC0415 - installed as an optional parser callback

    capture_exception(exception, additional_properties=additional_properties)


class PostHogHogQLBackendHooks(HogQLBackendHooks):
    def resolve_symbol(self, module: str, name: str) -> Any:
        return getattr(import_module(module), name)

    def create_default_query_modifiers(self) -> Any:
        from posthog.schema import HogQLQueryModifiers  # noqa: PLC0415 - keeps schema imports behind hook calls

        return HogQLQueryModifiers()

    def get_project_id_for_team(self, team_id: int) -> int:
        from posthog.models import Team  # noqa: PLC0415 - avoids importing Django models from the adapter module

        return Team.objects.only("project_id").get(id=team_id).project_id

    def get_query_provider(self):
        from posthog.hogql_query import PostHogQueryProvider  # noqa: PLC0415 - keeps query execution dependencies lazy

        return PostHogQueryProvider()

    def is_test_mode(self) -> bool:
        from django.conf import settings  # noqa: PLC0415 - keeps Django settings behind the host adapter

        return bool(settings.TEST)


def install_hogql_backend_hooks() -> None:
    set_hogql_backend_hooks(PostHogHogQLBackendHooks())
    set_parser_exception_reporter(_capture_parser_exception)
