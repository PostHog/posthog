from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import pagination, serializers, viewsets
from rest_framework.exceptions import ValidationError

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.insight_variable import InsightVariable


class InsightVariableSerializer(serializers.ModelSerializer):
    class Meta:
        model = InsightVariable

        fields = ["id", "name", "type", "default_value", "created_by", "created_at", "code_name", "values"]

        read_only_fields = ["id", "code_name", "created_by", "created_at"]

    def create(self, validated_data):
        validated_data["team_id"] = self.context["team_id"]
        validated_data["created_by"] = self.context["request"].user

        # Strips non alphanumeric values from name (other than spaces)
        validated_data["code_name"] = (
            "".join(n for n in validated_data["name"] if n.isalnum() or n == " ").replace(" ", "_").lower()
        )

        count = InsightVariable.objects.filter(
            team_id=self.context["team_id"], code_name=validated_data["code_name"]
        ).count()

        if count > 0:
            raise ValidationError("Variable with name already exists")

        return InsightVariable.objects.create(**validated_data)


class InsightVariablePagination(pagination.PageNumberPagination):
    page_size = 500


class InsightVariableViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    queryset = InsightVariable.objects.all()
    pagination_class = InsightVariablePagination
    serializer_class = InsightVariableSerializer
    filter_backends = [DjangoFilterBackend]


def map_stale_to_latest(stale_variables: dict, latest_variables: list[InsightVariable]) -> dict:
    # Keep the variables in an insight up to date based on variable code names that exist
    current_variables = stale_variables
    insight_variables = latest_variables
    final_variables = {}

    # Create a lookup for insight variables by code_name for quick access
    insight_variables_by_code_name = {var.code_name: var for var in insight_variables}

    # For each variable in current_variables, update with data from insight_variables if code_name matches
    for _, v in current_variables.items():
        code_name = v.get("code_name")
        if code_name in insight_variables_by_code_name:
            # Update the variable with corresponding data from insight_variables
            matched_var = insight_variables_by_code_name[code_name]
            # Add attributes from matched_var that can be serialized to JSON
            final_variables[str(matched_var.id)] = {
                **v,
                "code_name": matched_var.code_name,
                "variableId": str(matched_var.id),
            }

    return final_variables
