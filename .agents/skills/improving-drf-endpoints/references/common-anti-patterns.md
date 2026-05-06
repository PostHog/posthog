# Common Anti-Patterns — Before/After

## 1. Missing help_text

```python
# Before
class ActionSerializer(serializers.ModelSerializer):
    name = serializers.CharField()
    steps = serializers.ListField(child=ActionStepSerializer())
    deleted = serializers.BooleanField()

# After
class ActionSerializer(serializers.ModelSerializer):
    name = serializers.CharField(
        help_text="Human-readable name for the action. Shown in the UI and used for filtering."
    )
    steps = serializers.ListField(
        child=ActionStepSerializer(),
        help_text="Ordered list of match conditions. An event matches if any step matches.",
    )
    deleted = serializers.BooleanField(
        help_text="Whether the action has been soft-deleted. Deleted actions are excluded from queries.",
    )
```

## 2. Bare JSONField

```python
# Before — generates generic object, agents can't construct valid input
class HogFunctionSerializer(serializers.ModelSerializer):
    inputs = serializers.JSONField(required=False)

# After — typed via Pydantic model
from pydantic import BaseModel

class HogFunctionInputs(BaseModel):
    name: str
    value: str | int | bool | None = None
    secret: bool = False

@extend_schema_field(HogFunctionInputs)  # type: ignore[arg-type]
class HogFunctionInputsField(serializers.JSONField):
    pass

class HogFunctionSerializer(serializers.ModelSerializer):
    inputs = HogFunctionInputsField(
        required=False,
        help_text="Input configuration for the Hog function. Each input has a name, value, and secret flag.",
    )
```

## 3. Bare ListField without child

```python
# Before — generates z.array(z.unknown())
class BatchSerializer(serializers.Serializer):
    ids = serializers.ListField(required=True)

# After — generates z.array(z.string())
class BatchSerializer(serializers.Serializer):
    ids = serializers.ListField(
        child=serializers.CharField(),
        min_length=1,
        max_length=100,
        help_text="List of resource IDs to process.",
    )
```

## 4. Plain ViewSet with manual validation and no schema

```python
# Before — drf-spectacular discovers nothing
class LLMProxyViewSet(viewsets.ViewSet):
    def completion(self, request, *args, **kwargs):
        serializer = LLMProxyCompletionSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)
        data = serializer.validated_data
        # ...

# After — @validated_request handles validation + OpenAPI
from drf_spectacular.utils import OpenApiResponse
from posthog.api.mixins import validated_request

class LLMProxyViewSet(viewsets.ViewSet):
    @validated_request(
        request_serializer=LLMProxyCompletionSerializer,
        responses={200: OpenApiResponse(response=LLMProxyResponseSerializer, description="LLM completion response")},
        summary="LLM completion",
        description="Proxy a completion request to the configured LLM provider.",
    )
    def completion(self, request, *args, **kwargs):
        data = request.validated_data
        # ...
```

## 5. @extend_schema on class instead of method

```python
# Before — decorator on class does nothing for APIView
@extend_schema(request=MySerializer)
class MyView(APIView):
    def post(self, request):
        ...

# After — on the actual handler
class MyView(APIView):
    @extend_schema(
        request=MySerializer,
        responses={201: MyResponseSerializer},
        summary="Create a thing",
    )
    def post(self, request):
        ...
```

## 6. Generic error response types

```python
# Before — z.object({}) for errors
@extend_schema(
    responses={
        200: DashboardSerializer,
        400: OpenApiTypes.OBJECT,
        500: OpenApiTypes.OBJECT,
    },
)

# After — descriptive responses
@extend_schema(
    responses={
        200: DashboardSerializer,
        400: OpenApiResponse(description="Validation error — field-level error details"),
        404: OpenApiResponse(description="Dashboard not found"),
    },
)
```

## 7. Wrong 204 No Content response annotation

```python
# Before — OpenApiTypes.NONE produces {"schema": null}, which is invalid OpenAPI
# and breaks Orval validation
@extend_schema(responses={204: OpenApiTypes.NONE})
def delete(self, request, **kwargs):
    ...
    return Response(status=status.HTTP_204_NO_CONTENT)

# After — None means "no response body", which is correct for 204
@extend_schema(responses={204: None})
def delete(self, request, **kwargs):
    ...
    return Response(status=status.HTTP_204_NO_CONTENT)
```

## 8. Unannotated SerializerMethodField

```python
# Before — return type is unknown in OpenAPI
class TeamSerializer(serializers.ModelSerializer):
    member_count = serializers.SerializerMethodField()

    def get_member_count(self, obj):
        return obj.members.count()

# After — return type declared
from drf_spectacular.utils import extend_schema_field

class TeamSerializer(serializers.ModelSerializer):
    member_count = serializers.SerializerMethodField(
        help_text="Number of members in this team"
    )

    @extend_schema_field(serializers.IntegerField())
    def get_member_count(self, obj):
        return obj.members.count()
```

## 9. Custom @action without schema annotation

```python
# Before — MCP tool gets zero parameters
@action(detail=False, methods=["post"], url_path="evaluate")
def evaluate(self, request, **kwargs):
    serializer = EvaluateRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    ...

# After — schema declared
@extend_schema(
    request=EvaluateRequestSerializer,
    responses={200: EvaluateResponseSerializer},
    summary="Run evaluation",
    description="Execute an evaluation run against the specified dataset.",
)
@action(detail=False, methods=["post"], url_path="evaluate")
def evaluate(self, request, **kwargs):
    serializer = EvaluateRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    ...
```

## 10. CharField where ChoiceField is appropriate

```python
# Before — any string accepted, agents guess at values
status = serializers.CharField(help_text="The status to filter by")

# After — valid values enumerated
status = serializers.ChoiceField(
    choices=["active", "archived", "deleted"],
    help_text="Filter by resource status.",
)
```

## 11. Same serializer for read and write with computed fields

```python
# Before — computed fields cause validation errors on write
class ExperimentSerializer(serializers.ModelSerializer):
    results = serializers.JSONField(read_only=True)  # Computed
    created_by = UserBasicSerializer(read_only=True)  # Computed

    class Meta:
        model = Experiment
        fields = "__all__"

# After — separate serializers
class ExperimentWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Experiment
        fields = ["name", "description", "feature_flag_key", "filters"]

class ExperimentReadSerializer(serializers.ModelSerializer):
    results = serializers.JSONField(read_only=True)
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = Experiment
        fields = "__all__"

# In the viewset:
def get_serializer_class(self):
    if self.action in ("create", "update", "partial_update"):
        return ExperimentWriteSerializer
    return ExperimentReadSerializer
```
