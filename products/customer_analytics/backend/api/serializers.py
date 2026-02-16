import json

from rest_framework import serializers

from products.customer_analytics.backend.models import CustomerProfileConfig


class CustomerProfileConfigSerializer(serializers.ModelSerializer):
    content = serializers.JSONField(required=False, allow_null=True, default=dict)
    sidebar = serializers.JSONField(required=False, allow_null=True, default=dict)

    class Meta:
        model = CustomerProfileConfig
        fields = [
            "id",
            "scope",
            "content",
            "sidebar",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
        ]

    @staticmethod
    def validate_scope(value):
        if value not in dict(CustomerProfileConfig.Scope.choices):
            raise serializers.ValidationError(
                f"Invalid scope '{value}'. Must be one of: {', '.join(dict(CustomerProfileConfig.Scope.choices).keys())}"
            )
        return value

    def validate_content(self, value):
        return self._validate_json(field="content", value=value)

    def validate_sidebar(self, value):
        return self._validate_json(field="sidebar", value=value)

    def _validate_json(self, field: str, value):
        self.fields[field].run_validation(value)

        if value is None:
            return {}

        if not isinstance(value, dict | list):
            raise serializers.ValidationError(f"Invalid value for field '{field}'")

        try:
            json.dumps(value)
        except (ValueError, TypeError):
            raise serializers.ValidationError(f"Invalid value for field '{field}'")

        return value

    def create(self, validated_data):
        request = self.context["request"]
        validated_data["created_by"] = request.user
        validated_data["team_id"] = self.context["team_id"]
        return super().create(validated_data)
