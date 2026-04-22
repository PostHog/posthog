# Quick Reference — "I See X, Do Y"

| You see this                                             | Do this                                                                                                 | Details                                          |
| -------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- | ------------------------------------------------ |
| `serializers.JSONField()`                                | Create custom field class + `@extend_schema_field(PydanticModel)`                                       | [serializer-fields.md](serializer-fields.md)     |
| `serializers.ListField()` without `child=`               | Add `child=serializers.CharField()` (or appropriate type)                                               | [serializer-fields.md](serializer-fields.md)     |
| `serializers.DictField()` without `child=`               | Add `child=` with typed values                                                                          | [serializer-fields.md](serializer-fields.md)     |
| Any field without `help_text`                            | Add `help_text="..."` describing purpose, format, constraints                                           | [serializer-fields.md](serializer-fields.md)     |
| `CharField` for a fixed set of values                    | Change to `ChoiceField(choices=[...])`                                                                  | [serializer-fields.md](serializer-fields.md)     |
| `SerializerMethodField` without annotation               | Add `@extend_schema_field(...)` on its `get_*` method                                                   | [serializer-fields.md](serializer-fields.md)     |
| `request: ValidatedRequest` with typed DTO               | Use `TypedRequest[MyDTO]` for type-safe `validated_data`                                                | [viewset-annotations.md](viewset-annotations.md) |
| Plain `ViewSet` with `serializer.is_valid()`             | Replace with `@validated_request` decorator                                                             | [viewset-annotations.md](viewset-annotations.md) |
| `@action` without `@extend_schema`                       | Add `@extend_schema(request=..., responses=...)` above `@action`                                        | [viewset-annotations.md](viewset-annotations.md) |
| `@extend_schema` on class (not method)                   | Move to the actual handler method (`get`, `post`, `create`, etc.)                                       | [viewset-annotations.md](viewset-annotations.md) |
| `responses={400: OpenApiTypes.OBJECT}`                   | Use `OpenApiResponse(description="...")`                                                                | [viewset-annotations.md](viewset-annotations.md) |
| Same serializer for read + write with `read_only` fields | Split into separate read/write serializers                                                              | [viewset-annotations.md](viewset-annotations.md) |
| Custom `@action` returning non-paginated data            | Set `pagination_class=None` on the action                                                               | [viewset-annotations.md](viewset-annotations.md) |
| `fields = "__all__"` on ModelSerializer                  | Explicitly list fields — `__all__` leaks internal fields to the API                                     | General DRF practice                             |
| Endpoint returns raw dict/list (no response serializer)  | Create a response serializer so downstream types are generated                                          | [viewset-annotations.md](viewset-annotations.md) |
| Streaming/SSE endpoint                                   | Use `@extend_schema(request=InputSerializer, responses={(200, "text/event-stream"): OpenApiTypes.STR})` | [viewset-annotations.md](viewset-annotations.md) |
