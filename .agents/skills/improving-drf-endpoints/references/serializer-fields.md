# Serializer Field Patterns

## help_text on every field

`help_text` flows through the entire pipeline to become the OpenAPI field description,
the Zod `.describe()` string, and ultimately what an LLM reads when deciding how to fill a parameter.

```python
# Bad — agent has no idea what this field expects
name = serializers.CharField()

# Good — clear, actionable description
name = serializers.CharField(
    help_text="Human-readable name for the action. Used in the UI and API responses."
)
```

Guidelines for writing `help_text`:

- Describe the purpose, not just the type ("UUID of the parent dashboard" not "a UUID")
- Mention format constraints ("ISO 8601 datetime string", "comma-separated list")
- List valid values for constrained fields ("One of: active, archived, deleted")
- Note defaults if non-obvious ("Defaults to the current project's timezone")
- Be specific about what happens with null/empty ("Pass null to remove the filter")

## ListField — always specify child=

A bare `ListField()` produces `z.unknown()` in the generated Zod schema.

```python
# Bad — Orval generates z.array(z.unknown())
tags = serializers.ListField()

# Good — generates z.array(z.string())
tags = serializers.ListField(
    child=serializers.CharField(),
    help_text="Tags to apply to this resource. Each tag is a plain string.",
)

# Good — typed child for complex items
steps = serializers.ListField(
    child=ActionStepSerializer(),
    help_text="Ordered list of action steps. Each step defines a match condition.",
)
```

## JSONField — use @extend_schema_field with a typed schema

Bare `JSONField` produces a generic object schema. The fix is a custom field class
with `@extend_schema_field` pointing to a Pydantic model or inline schema.

The canonical pattern is in `posthog/api/alert.py`:

```python
from drf_spectacular.utils import extend_schema_field
from pydantic import BaseModel

# 1. Define the schema (Pydantic model or OpenAPI-compatible class)
class AlertCondition(BaseModel):
    type: str
    threshold: float
    operator: str

# 2. Create a custom field class with the decorator
@extend_schema_field(AlertCondition)  # type: ignore[arg-type]
class AlertConditionField(serializers.JSONField):
    pass

# 3. Use the custom field in the serializer
class AlertSerializer(serializers.ModelSerializer):
    condition = AlertConditionField(
        required=False,
        allow_null=True,
        help_text="Condition that triggers the alert. See AlertCondition schema.",
    )
```

For simpler cases where a full Pydantic model is overkill, use `OpenApiTypes`:

```python
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field

@extend_schema_field(OpenApiTypes.OBJECT)
class MetadataField(serializers.JSONField):
    """At minimum, this tells Orval it's an object, not unknown."""
    pass
```

## SerializerMethodField — annotate the getter

Without `@extend_schema_field`, drf-spectacular can't infer the return type.

```python
# Bad — return type unknown in OpenAPI
class TeamSerializer(serializers.ModelSerializer):
    member_count = serializers.SerializerMethodField()

    def get_member_count(self, obj):
        return obj.members.count()

# Good — explicit return type
class TeamSerializer(serializers.ModelSerializer):
    member_count = serializers.SerializerMethodField()

    @extend_schema_field(serializers.IntegerField(help_text="Number of team members"))
    def get_member_count(self, obj):
        return obj.members.count()
```

For complex return types:

```python
@extend_schema_field(serializers.ListField(child=serializers.CharField()))
def get_redirect_uris_list(self, instance) -> list[str]:
    return instance.redirect_uris.split() if instance.redirect_uris else []
```

## ChoiceField — explicit choices

```python
# Bad — valid values not discoverable
status = serializers.CharField()

# Good — choices appear in OpenAPI enum
status = serializers.ChoiceField(
    choices=["active", "archived", "deleted"],
    help_text="Current status of the resource.",
)
```

## DictField — typed values

```python
# Bad — generic dict
properties = serializers.DictField()

# Good — typed values
properties = serializers.DictField(
    child=serializers.CharField(),
    help_text="Key-value pairs of event properties. Keys and values are strings.",
)
```
