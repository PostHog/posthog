from pydantic import BaseModel
from rest_framework import serializers


class PydanticField(serializers.JSONField):
    """
    A field that serializes/deserializes Pydantic models while maintaining type safety.
    """

    def __init__(self, pydantic_model: type[BaseModel], **kwargs):
        self.pydantic_model = pydantic_model
        super().__init__(**kwargs)

    def to_representation(self, value):
        if hasattr(value, "model_dump"):
            return value.model_dump()
        return value

    def to_internal_value(self, data):
        # Let the parent handle basic JSON validation first
        data = super().to_internal_value(data)
        try:
            # Validate with Pydantic model
            validated_instance = self.pydantic_model.model_validate(data or {})
            return validated_instance.model_dump()
        except Exception as e:
            raise serializers.ValidationError(f"Invalid data for {self.pydantic_model.__name__}") from e
