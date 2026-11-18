from typing import TypedDict, cast

from rest_framework import serializers
from rest_framework.exceptions import ErrorDetail
from rest_framework.settings import api_settings


class OfflineEvaluationValidationErrorSerializer(serializers.Serializer):
    code = serializers.CharField(help_text="Stable validation error code.")
    detail = serializers.CharField(help_text="Explanation of the invalid value.")
    attr = serializers.CharField(
        allow_null=True, help_text="Invalid field path, with dot-separated fields and zero-based batch indexes."
    )


class OfflineEvaluationErrorSerializer(serializers.Serializer):
    type = serializers.CharField(required=False, help_text="Error category for standard API errors.")
    code = serializers.CharField(help_text="Stable error code.")
    detail = serializers.CharField(help_text="Explanation of the rejected request.")
    attr = serializers.CharField(
        required=False, allow_null=True, help_text="Invalid field, including batch entry index."
    )
    expected_item_count = serializers.IntegerField(required=False, allow_null=True, help_text="Declared item count.")
    expected_result_count = serializers.IntegerField(
        required=False, allow_null=True, help_text="Declared result count."
    )
    accepted_item_count = serializers.IntegerField(required=False, help_text="Accepted items at failed completion.")
    accepted_result_count = serializers.IntegerField(required=False, help_text="Accepted results at failed completion.")

    def get_fields(self) -> dict[str, serializers.Field]:
        fields = super().get_fields()
        fields["errors"] = OfflineEvaluationValidationErrorSerializer(
            many=True, required=False, help_text="All validation errors found in the request."
        )
        return fields


class ValidationErrorEntry(TypedDict):
    code: str
    detail: str
    attr: str | None


def validation_errors(detail: object, path: tuple[str, ...] = ()) -> list[ValidationErrorEntry]:
    if isinstance(detail, dict):
        errors: list[ValidationErrorEntry] = []
        for field, value in cast(dict[str | int, object], detail).items():
            field_path = path if field in (api_settings.NON_FIELD_ERRORS_KEY, "__all__") else (*path, str(field))
            errors.extend(validation_errors(value, field_path))
        return errors
    if isinstance(detail, list):
        errors = []
        for index, value in enumerate(cast(list[object], detail)):
            item_path = (*path, str(index)) if isinstance(value, dict | list) else path
            errors.extend(validation_errors(value, item_path))
        return errors
    code = (detail.code or "invalid") if isinstance(detail, ErrorDetail) else "invalid"
    return [
        {"code": "invalid_input" if code == "invalid" else code, "detail": str(detail), "attr": ".".join(path) or None}
    ]
