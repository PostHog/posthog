from posthog.test.base import BaseTest

from posthog.hogql import ast
from posthog.hogql.visitor import TraversingVisitor

from posthog.hogql_django_provider import DjangoDataProvider
from posthog.models import Team

from products.actions.backend.models.action import Action


class _CollectCalls(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[ast.Call] = []

    def visit_call(self, node: ast.Call) -> None:
        self.calls.append(node)
        super().visit_call(node)


class TestDjangoDataProviderActionExpr(BaseTest):
    def test_sibling_team_action_compiles_with_its_own_team_settings(self):
        # An action can be referenced across teams within one project (the action()
        # function looks up project-wide). Its step filters must compile with the
        # owning team's settings — here, that team's path cleaning rules.
        sibling = Team.objects.create(
            organization=self.organization,
            project=self.project,
            path_cleaning_filters=[{"alias": "/cleaned", "regex": "/replace-me"}],
        )
        action = Action.objects.create(
            team=sibling,
            name="cleaned path action",
            steps_json=[
                {
                    "event": "$pageview",
                    "properties": [
                        {
                            "key": "$pathname",
                            "type": "event",
                            "operator": "is_cleaned_path_exact",
                            "value": "/replace-me",
                        }
                    ],
                }
            ],
        )

        expr = DjangoDataProvider(team=self.team).action_expr(action.pk)

        assert expr is not None
        collector = _CollectCalls()
        collector.visit(expr)
        cleaning_calls = [
            call
            for call in collector.calls
            if call.name == "replaceRegexpAll"
            and any(isinstance(arg, ast.Constant) and arg.value == "/cleaned" for arg in call.args)
        ]
        assert cleaning_calls, "sibling team's path cleaning rules were not applied to the action's step filters"
