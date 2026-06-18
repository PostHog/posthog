from typing import Any

from common.hogql.dependencies import HogQLVariableProvider, InsightVariableDefinition

from posthog.models.team.team import Team

from products.product_analytics.backend.models.insight_variable import InsightVariable


class PostHogVariableProvider(HogQLVariableProvider):
    def list_insight_variables(self, *, team: Team, variable_ids: list[Any]) -> list[InsightVariableDefinition]:
        return [
            InsightVariableDefinition(
                code_name=str(variable.code_name),
                default_value=variable.default_value,
            )
            for variable in InsightVariable.objects.filter(team_id=team.pk, id__in=variable_ids).all()
        ]
