from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models.batch_imports import BatchImport, ContentType
from posthog.models.user import User


class BatchImportSerializer(serializers.ModelSerializer):
    """Serializer for BatchImport model"""

    created_by = serializers.SerializerMethodField()

    class Meta:
        model = BatchImport
        fields = [
            "id",
            "team_id",
            "created_at",
            "updated_at",
            "state",
            "created_by",
            "status",
            "status_message",
            "import_config",
        ]
        read_only_fields = [
            "id",
            "team_id",
            "created_at",
            "updated_at",
            "state",
        ]

    def create(self, validated_data: dict) -> BatchImport:
        validated_data["team_id"] = self.context["team_id"]
        validated_data["created_by_id"] = self.context["request"].user.id

        if "import_config" in validated_data:
            validated_data["import_config"] = validated_data.pop("import_config")
        return BatchImport.objects.create(**validated_data)

    def get_created_by(self, obj):
        if obj.created_by_id:
            try:
                user = User.objects.get(id=obj.created_by_id)
                return UserBasicSerializer(user).data
            except User.DoesNotExist:
                return None
        return None


class BatchImportS3SourceCreateSerializer(BatchImportSerializer):
    """Serializer for creating BatchImports with config builder methods"""

    content_type = serializers.ChoiceField(
        choices=["mixpanel", "captured", "amplitude"],
        write_only=True,
        required=True,
    )
    source_type = serializers.ChoiceField(
        choices=["s3"],
        write_only=True,
        required=True,
    )
    s3_bucket = serializers.CharField(write_only=True, required=False)
    s3_prefix = serializers.CharField(write_only=True, required=False)
    s3_region = serializers.CharField(write_only=True, required=False)
    access_key = serializers.CharField(write_only=True, required=False)
    secret_key = serializers.CharField(write_only=True, required=False)

    class Meta:
        model = BatchImport
        fields = [
            "id",
            "team_id",
            "created_at",
            "updated_at",
            "state",
            "status",
            "status_message",
            "import_config",
            "content_type",
            "source_type",
            "s3_bucket",
            "s3_prefix",
            "s3_region",
            "access_key",
            "secret_key",
        ]
        read_only_fields = [
            "id",
            "team_id",
            "created_at",
            "updated_at",
            "state",
            "status",
            "status_message",
            "import_config",
        ]

    def create(self, validated_data: dict, **kwargs) -> BatchImport:
        """Create BatchImport using config builder pattern."""
        batch_import = BatchImport(
            team_id=self.context["team_id"],
            created_by_id=self.context["request"].user.id,
        )

        content_type_map = {
            "mixpanel": ContentType.MIXPANEL,
            "amplitude": ContentType.AMPLITUDE,
            "captured": ContentType.CAPTURED,
        }

        content_type = content_type_map[validated_data["content_type"]]

        batch_import.config.json_lines(content_type).from_s3(
            bucket=validated_data["s3_bucket"],
            prefix=validated_data["s3_prefix"],
            region=validated_data["s3_region"],
            access_key_id=validated_data["access_key"],
            secret_access_key=validated_data["secret_key"],
        ).to_kafka(
            topic=f"events_plugin_ingestion_historical",
            send_rate=1000,
            transaction_timeout_seconds=60,
        )

        batch_import.save()
        return batch_import


class BatchImportResponseSerializer(serializers.ModelSerializer):
    """Serializer for BatchImport responses that matches frontend expectations"""

    created_by = serializers.SerializerMethodField()
    source_type = serializers.SerializerMethodField()
    start_date = serializers.SerializerMethodField()
    end_date = serializers.SerializerMethodField()
    content_type = serializers.SerializerMethodField()
    error = serializers.CharField(source="status_message", allow_null=True)

    class Meta:
        model = BatchImport
        fields = [
            "id",
            "source_type",
            "content_type",
            "status",
            "start_date",
            "end_date",
            "created_by",
            "created_at",
            "error",
            "state",
        ]

    def get_source_type(self, obj):
        """Extract source type from import_config"""
        source = obj.import_config.get("source", {})
        return source.get("type", "s3")

    def get_start_date(self, obj):
        """Extract start date from import_config"""
        source = obj.import_config.get("source", {})
        return source.get("start")

    def get_end_date(self, obj):
        """Extract end date from import_config"""
        source = obj.import_config.get("source", {})
        return source.get("end")

    def get_content_type(self, obj):
        """Extract content type from import_config"""
        data_format = obj.import_config.get("data_format", {})
        content = data_format.get("content", {})
        return content.get("type", "captured")

    def get_created_by(self, obj):
        if obj.created_by_id:
            try:
                user = User.objects.get(id=obj.created_by_id)
                return UserBasicSerializer(user).data
            except User.DoesNotExist:
                return None
        return None


class BatchImportViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """Viewset for BatchImport model"""

    scope_object = "INTERNAL"
    queryset = BatchImport.objects.all()
    serializer_class = BatchImportSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["status"]
    search_fields = ["status_message"]
    ordering_fields = ["created_at", "updated_at", "status"]
    ordering = ["-created_at"]

    def get_serializer_class(self):
        """Use the correct serializer based on the source type"""
        if self.action == "create":
            return BatchImportS3SourceCreateSerializer
        return BatchImportSerializer

    def safely_get_queryset(self, queryset=None):
        if queryset is None:
            queryset = self.get_queryset()
        return queryset.filter(team_id=self.team_id)

    def list(self, request: Request, **kwargs) -> Response:
        """List managed migrations using the response serializer"""
        queryset = self.safely_get_queryset()
        queryset = self.filter_queryset(queryset)
        page = self.paginate_queryset(queryset)

        if page is not None:
            serializer = BatchImportResponseSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = BatchImportResponseSerializer(queryset, many=True)
        return Response({"results": serializer.data})

    def create(self, request: Request, **kwargs) -> Response:
        """Create a new managed migration/batch import."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        migration = serializer.save()

        response_serializer = BatchImportResponseSerializer(migration)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    @action(methods=["POST"], detail=True)
    def pause(self, request: Request, pk=None) -> Response:
        """Pause a running batch import."""
        batch_import = self.get_object()

        if batch_import.status != BatchImport.Status.RUNNING:
            return Response(
                {"error": "only running imports can be paused"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        batch_import.status = BatchImport.Status.PAUSED
        batch_import.status_message = "Paused by user"
        batch_import.save(update_fields=["status", "status_message", "updated_at"])

        return Response({"status": "paused"})

    @action(methods=["POST"], detail=True)
    def resume(self, request: Request, pk=None) -> Response:
        """Resume a paused batch import."""
        batch_import = self.get_object()

        if batch_import.status != BatchImport.Status.PAUSED:
            return Response({"error": "Only paused imports can be resumed"}, status=status.HTTP_400_BAD_REQUEST)

        batch_import.status = BatchImport.Status.RUNNING
        batch_import.status_message = "Resumed by user"
        batch_import.save(update_fields=["status", "status_message", "updated_at"])

        return Response({"status": "resumed"})
