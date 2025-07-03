from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
import posthoganalytics
import uuid
from datetime import timedelta

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models.batch_imports import BatchImport, ContentType, DateRangeExportSource
from posthog.models.user import User
from posthog.kafka_client.topics import KAFKA_EVENTS_PLUGIN_INGESTION_HISTORICAL


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
            "display_status_message",
            "import_config",
        ]
        read_only_fields = [
            "id",
            "team_id",
            "created_at",
            "updated_at",
            "state",
            "display_status_message",
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
            "display_status_message",
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
            "display_status_message",
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
            topic=KAFKA_EVENTS_PLUGIN_INGESTION_HISTORICAL,
            send_rate=1000,
            transaction_timeout_seconds=60,
        )

        batch_import.save()
        return batch_import


class BatchImportDateRangeSourceCreateSerializer(BatchImportSerializer):
    """Serializer for creating BatchImports with date range source (mixpanel, amplitude, etc.)"""

    start_date = serializers.DateTimeField(write_only=True, required=True)
    end_date = serializers.DateTimeField(write_only=True, required=True)
    source_type = serializers.ChoiceField(
        choices=["mixpanel", "amplitude"],
        write_only=True,
        required=True,
    )
    content_type = serializers.ChoiceField(
        choices=["mixpanel", "amplitude"],
        write_only=True,
        required=True,
    )
    access_key = serializers.CharField(write_only=True, required=True)
    secret_key = serializers.CharField(write_only=True, required=True)

    class Meta:
        model = BatchImport
        fields = [
            "id",
            "team_id",
            "created_at",
            "updated_at",
            "state",
            "status",
            "display_status_message",
            "import_config",
            "start_date",
            "end_date",
            "source_type",
            "content_type",
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
            "display_status_message",
            "import_config",
        ]

    def validate(self, data):
        """Validate the date range doesn't exceed 1 year"""
        data = super().validate(data)

        start_date = data.get("start_date")
        end_date = data.get("end_date")

        if start_date and end_date:
            if end_date <= start_date:
                raise serializers.ValidationError("End date must be after start date")

            one_year_after_start = start_date + timedelta(days=365)
            if end_date > one_year_after_start:
                raise serializers.ValidationError(
                    "Date range cannot exceed 1 year. Please create multiple migration jobs for longer periods."
                )

        return data

    def create(self, validated_data: dict, **kwargs) -> BatchImport:
        """Create a new BatchImport from Date Range Source"""
        validated_data["team_id"] = self.context["team_id"]
        source_type = validated_data["source_type"]

        if source_type in ["amplitude", "mixpanel"]:
            batch_import = BatchImport(
                team_id=self.context["team_id"],
                created_by_id=self.context["request"].user.id,
            )

            batch_import.config.json_lines(ContentType(validated_data["content_type"])).from_date_range(
                start_date=validated_data["start_date"].isoformat(),
                end_date=validated_data["end_date"].isoformat(),
                access_key=validated_data["access_key"],
                secret_key=validated_data["secret_key"],
                export_source=DateRangeExportSource(source_type),
            ).to_kafka(
                topic=f"events_plugin_ingestion_historical",
                send_rate=1000,
                transaction_timeout_seconds=60,
            )

            batch_import.save()
            return batch_import
        else:
            raise serializers.ValidationError("Invalid source type")


class BatchImportResponseSerializer(serializers.ModelSerializer):
    """Serializer for BatchImport responses that matches frontend expectations"""

    created_by = serializers.SerializerMethodField()
    source_type = serializers.SerializerMethodField()
    start_date = serializers.SerializerMethodField()
    end_date = serializers.SerializerMethodField()
    content_type = serializers.SerializerMethodField()
    status_message = serializers.CharField(source="display_status_message", allow_null=True)

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
            "status_message",
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
            source_type = self.request.data.get("source_type")
            if source_type == "s3":
                return BatchImportS3SourceCreateSerializer
            elif source_type in ["mixpanel", "amplitude"]:
                return BatchImportDateRangeSourceCreateSerializer
            else:
                raise serializers.ValidationError("Invalid source type")
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
        existing_running_import = BatchImport.objects.filter(
            team_id=self.team_id, status=BatchImport.Status.RUNNING
        ).first()

        if existing_running_import:
            return Response(
                {
                    "error": "Cannot create a new batch import while another import is already running for this organization.",
                    "detail": f"Please wait for the current import (ID: {existing_running_import.id}) to complete or pause it before starting a new one.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        migration = serializer.save()

        source_type = request.data.get("source_type", "unknown")
        content_type = request.data.get("content_type", "unknown")

        distinct_id = (
            request.user.distinct_id
            if request.user.is_authenticated and request.user.distinct_id
            else str(uuid.uuid4())
        )

        posthoganalytics.capture(
            "batch import created",
            distinct_id=distinct_id,
            properties={
                "batch_import_id": migration.id,
                "source_type": source_type,
                "content_type": content_type,
                "team_id": self.team_id,
                "$process_person_profile": False,
            },
        )

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
