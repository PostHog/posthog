# ViewSet and Action Annotation Patterns

## @validated_request — the preferred decorator

`@validated_request` from `posthog/api/mixins.py` combines request validation,
query parameter validation, and `@extend_schema` in one decorator.
It sets `request.validated_data` and `request.validated_query_data` automatically.

```python
from posthog.api.mixins import validated_request
from drf_spectacular.utils import OpenApiResponse

class TaskViewSet(viewsets.ModelViewSet):
    @validated_request(
        query_serializer=TaskListQuerySerializer,
        responses={
            200: OpenApiResponse(response=TaskSerializer, description="List of tasks"),
        },
        summary="List tasks",
        description="Get a list of tasks for the current project, optionally filtered by repository.",
    )
    def list(self, request, *args, **kwargs):
        repository = request.validated_query_data["repository"]
        # ... use validated data directly
```

Use `@validated_request` when:

- The endpoint accepts a request body (`request_serializer=`)
- The endpoint accepts query parameters (`query_serializer=`)
- You want automatic validation before the method body runs

### TypedRequest — typed validated_data

By default `request.validated_data` is `dict[str, Any]`.
Use `TypedRequest[T]` from `posthog/api/mixins.py` to tell the type checker
the actual shape, especially with `DataclassSerializer` where `validated_data`
returns a dataclass instance:

```python
from posthog.api.mixins import TypedRequest, validated_request

class RepoViewSet(viewsets.GenericViewSet):
    @validated_request(
        request_serializer=CreateRepoInputSerializer,
        responses={201: OpenApiResponse(response=RepoSerializer, description="Created repo")},
    )
    def create(self, request: TypedRequest[CreateRepoInput], **kwargs) -> Response:
        data = request.validated_data  # type checker knows this is CreateRepoInput
        repo = api.create_repo(data, team_id=self.team_id)
        return Response(RepoSerializer(repo).data, status=status.HTTP_201_CREATED)
```

Use `TypedRequest[T]` when the validated data is a typed object (dataclass, Pydantic model).
For plain dict payloads, `ValidatedRequest` is fine.

## @extend_schema — for endpoints where @validated_request doesn't fit

Use `@extend_schema` directly when you only need schema metadata without validation,
or when the endpoint pattern doesn't match `@validated_request`.

```python
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiParameter

class SentimentViewSet(viewsets.ViewSet):
    @extend_schema(
        request=SentimentRequestSerializer,
        responses={
            200: SentimentBatchResponseSerializer,
            400: OpenApiResponse(description="Invalid request data"),
        },
        tags=["LLM Analytics"],
        summary="Analyze sentiment",
        description="Run sentiment analysis on a batch of LLM generations.",
    )
    def create(self, request, **kwargs):
        serializer = SentimentRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # ...
```

### Critical: decorate the right method

`@extend_schema` must go on the actual HTTP handler method, not on a helper or the class.

```python
# Bad — decorator on APIView class has no effect
@extend_schema(request=MySerializer)
class MyView(APIView):
    def post(self, request):  # This method needs the decorator
        ...

# Good — decorator on the handler method
class MyView(APIView):
    @extend_schema(request=MySerializer, responses={201: MyResponseSerializer})
    def post(self, request):
        ...
```

For inherited methods (`list`, `create`, `retrieve`, etc.), use `@extend_schema_view`:

```python
from drf_spectacular.utils import extend_schema_view, extend_schema

@extend_schema_view(
    list=extend_schema(description="List all feature flags for the project"),
    retrieve=extend_schema(description="Get a single feature flag by ID"),
)
class FeatureFlagViewSet(viewsets.ModelViewSet):
    serializer_class = FeatureFlagSerializer
    # ...
```

## Custom @action methods

Every `@action` needs explicit schema annotation. Without it,
drf-spectacular generates zero parameters.

```python
# Bad — no schema, MCP tool gets z.object({})
@action(detail=False, methods=["post"], url_path="test_hog")
def test_hog(self, request, **kwargs):
    serializer = TestHogRequestSerializer(data=request.data)
    ...

# Good — schema declared
@extend_schema(
    request=TestHogRequestSerializer,
    responses={200: TestHogResponseSerializer},
    summary="Test Hog evaluation code",
    description="Test Hog evaluation code against sample events without saving.",
)
@action(detail=False, methods=["post"], url_path="test_hog")
def test_hog(self, request, **kwargs):
    ...
```

Note: `@extend_schema` goes above `@action` in the decorator stack.

## Typed error responses

Generic `OpenApiTypes.OBJECT` tells downstream consumers nothing about the error shape.

```python
from drf_spectacular.types import OpenApiTypes

# Bad — agents can't parse error structure
@extend_schema(
    responses={
        200: MySerializer,
        400: OpenApiTypes.OBJECT,
    },
)

# Good — error shape is documented
@extend_schema(
    responses={
        200: MySerializer,
        400: OpenApiResponse(description="Validation failed — returns field-level errors"),
        404: OpenApiResponse(description="Resource not found"),
    },
)
```

For endpoints with a consistent error body, create a reusable error serializer:

```python
class ValidationErrorSerializer(serializers.Serializer):
    attr = serializers.CharField(help_text="Field that failed validation")
    code = serializers.CharField(help_text="Error code")
    detail = serializers.CharField(help_text="Human-readable error message")
```

## Pagination on custom actions

Custom `@action` methods inherit the parent viewset's pagination by default,
which may not be correct.

```python
# If your custom action returns a non-paginated response:
@action(detail=False, methods=["get"], pagination_class=None, filter_backends=[])
def summary(self, request, **kwargs):
    ...
```

## Request/response serializer splitting

When input and output shapes differ, use separate serializers:

```python
@extend_schema(
    request=CreateExperimentSerializer,      # Only writable fields
    responses={201: ExperimentSerializer},    # Full object with computed fields
)
def create(self, request, *args, **kwargs):
    ...
```

drf-spectacular's `COMPONENT_SPLIT_PATCH` setting (enabled by default) handles
the PATCH case automatically, creating separate schemas for PATCH vs POST
since PATCH doesn't require all fields.
