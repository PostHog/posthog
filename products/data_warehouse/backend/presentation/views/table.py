import re
import uuid
from typing import Any, cast

from django.conf import settings

import boto3
import posthoganalytics
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_field
from rest_framework import filters, parsers, request, response, serializers, status, viewsets

from posthog.schema import DatabaseSerializedFieldType

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database, SerializedField, get_data_warehouse_table_name, serialize_fields

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import action
from posthog.exceptions_capture import capture_exception
from posthog.models import Team
from posthog.models.user import User
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin
from posthog.rbac.user_access_control import UserAccessControlSerializerMixin
from posthog.tasks.warehouse import validate_data_warehouse_table_columns

from products.data_warehouse.backend.facade.api import get_s3_client
from products.warehouse_sources.backend.facade.api import (
    FILE_FORMAT_TO_TABLE_FORMAT,
    MAX_FILE_UPLOAD_SIZE_BYTES,
    SUPPORTED_FILE_FORMATS,
    build_file_upload_s3_path,
    build_file_upload_url_pattern,
    hosted_upload_s3_path,
)
from products.warehouse_sources.backend.facade.hogql import (
    CLICKHOUSE_HOGQL_MAPPING,
    SERIALIZED_FIELD_TO_CLICKHOUSE_MAPPING,
    get_view_or_table_by_name,
)
from products.warehouse_sources.backend.facade.models import (
    DataWarehouseCredential,
    DataWarehouseTable,
    ExternalDataSource,
    validate_warehouse_table_url_pattern,
)
from products.warehouse_sources.backend.presentation.views.external_data_source import (
    SimpleExternalDataSourceSerializers,
)

# Whole-request-body ceiling for the upload endpoint, checked from Content-Length before the
# multipart parser spools anything to disk. The per-file check only sees request.FILES["file"], so
# without this an authenticated caller could push many large parts through the parser and fill temp
# storage far past the per-file cap. The margin over the file cap covers the multipart envelope and
# the small form fields sent alongside the file.
MAX_UPLOAD_REQUEST_BODY_BYTES = MAX_FILE_UPLOAD_SIZE_BYTES + 1024 * 1024


def _delete_hosted_upload_file(table: DataWarehouseTable) -> None:
    """Best-effort removal of a self-managed table's backing file from PostHog's own bucket.

    Only ever touches files we host: `hosted_upload_s3_path` returns `None` for a customer-linked
    bucket, and a stored credential (the mark of a user-supplied bucket) is a further guard. Failures
    are swallowed so a storage hiccup can't block the table delete — the object simply lingers.
    """
    if table.credential_id is not None:
        return
    path = hosted_upload_s3_path(table.url_pattern)
    if path is None:
        return
    # The same uploaded file can back more than one table — `create_from_upload` doesn't claim
    # exclusive ownership of an upload — so only reclaim the object once no live table still points
    # at it. This keeps deleting one table from pulling the file out from under another, and stops a
    # table whose file is still in use from having its object removed.
    if (
        DataWarehouseTable.objects.filter(team_id=table.team_id, url_pattern=table.url_pattern, deleted=False)
        .exclude(pk=table.pk)
        .exists()
    ):
        return
    try:
        get_s3_client().rm(path)
    except Exception as e:
        capture_exception(e)


class CredentialSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = DataWarehouseCredential
        fields = ["id", "created_by", "created_at", "access_key", "access_secret"]
        read_only_fields = [
            "id",
            "created_by",
            "created_at",
        ]
        extra_kwargs = {"access_key": {"write_only": "True"}, "access_secret": {"write_only": "True"}}


class TableSerializer(UserAccessControlSerializerMixin, serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    credential = CredentialSerializer()
    columns = serializers.SerializerMethodField(read_only=True)
    hogql_name = serializers.SerializerMethodField(
        read_only=True,
        help_text="Dotted name the table is queried by in HogQL (e.g. `googleanalytics.devices` or "
        "`postgres.<prefix>.<table>`), as opposed to `name`, which is the underlying storage identifier.",
    )
    external_data_source = SimpleExternalDataSourceSerializers(read_only=True)
    external_schema = serializers.SerializerMethodField(read_only=True)
    options = serializers.DictField(required=False, default=dict)

    class Meta:
        model = DataWarehouseTable
        fields = [
            "id",
            "deleted",
            "name",
            "hogql_name",
            "format",
            "created_by",
            "created_at",
            "url_pattern",
            "credential",
            "columns",
            "external_data_source",
            "external_schema",
            "options",
            "user_access_level",
        ]
        read_only_fields = [
            "id",
            "created_by",
            "created_at",
            "hogql_name",
            "columns",
            "external_data_source",
            "external_schema",
            "user_access_level",
        ]

    @extend_schema_field(serializers.CharField())
    def get_hogql_name(self, table: DataWarehouseTable) -> str:
        return get_data_warehouse_table_name(table.external_data_source, table.name)

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_columns(self, table: DataWarehouseTable) -> list[SerializedField]:
        # Callers that only need the table list (e.g. a table picker) skip the expensive HogQL field
        # serialization by passing include_columns=false — it serializes columns for every row.
        if not self.context.get("include_columns", True):
            return []
        database = self.context.get("database", None)
        if not database:
            database = Database.create_for(
                team_id=self.context["team_id"],
                user=cast(User, self.context["request"].user),
            )

        if database.has_table(table.name):
            fields = database.get_table(table.name).fields
        else:
            fields = table.hogql_definition().fields

        serializes_fields = serialize_fields(
            fields,
            HogQLContext(database=database, team_id=self.context["team_id"]),
            table.name_chain,
            table.columns,
            table_type="external",
        )

        return [
            SerializedField(
                key=field.name,
                name=field.name,
                type=field.type,
                schema_valid=field.schema_valid,
                fields=field.fields,
                table=field.table,
                chain=field.chain,
            )
            for field in serializes_fields
        ]

    @extend_schema_field(serializers.DictField(allow_null=True))
    def get_external_schema(self, instance: DataWarehouseTable):
        from products.warehouse_sources.backend.presentation.views.external_data_schema import (
            SimpleExternalDataSchemaSerializer,
        )

        return SimpleExternalDataSchemaSerializer(instance.externaldataschema_set.first(), read_only=True).data or None

    def create(self, validated_data):
        team_id = self.context["team_id"]

        validated_data["team_id"] = team_id
        validated_data["created_by"] = cast(User, self.context["request"].user)
        credential = validated_data.get("credential")

        if not credential:
            raise serializers.ValidationError("Credentials are required")

        access_key: str | None = credential.get("access_key")
        access_secret: str | None = credential.get("access_secret")

        # CRITICAL: users MUST provide an access key and secret, otherwise we'll fall back to using the EC2 node's internal role.
        # this would allow an external user to then access one of PostHog's internal S3 buckets
        if not access_key or not access_secret:
            raise serializers.ValidationError("Access key and secret are required")
        if len(access_key.strip()) == 0 or len(access_secret.strip()) == 0:
            raise serializers.ValidationError("Access key and secret can't be blank")

        validated_data["credential"] = DataWarehouseCredential.objects.create(
            team_id=team_id,
            access_key=access_key,
            access_secret=access_secret,
        )
        table = DataWarehouseTable(**validated_data)
        if table._is_csv_format() and table.csv_allow_double_quotes is not None:
            try:
                table._validate_csv_double_quotes_setting()
            except Exception as err:
                raise serializers.ValidationError(str(err))
        try:
            table.columns = table.get_columns()
        except Exception as err:
            raise serializers.ValidationError(str(err))
        try:
            table.save()
        except Exception as err:
            raise serializers.ValidationError(str(err))

        validate_data_warehouse_table_columns.delay(self.context["team_id"], str(table.id))

        return table

    def validate_url_pattern(self, url_pattern):
        s3_domain = settings.DATAWAREHOUSE_BUCKET_DOMAIN
        if s3_domain in url_pattern:
            raise serializers.ValidationError("Cant use this bucket")

        is_valid, error_message = validate_warehouse_table_url_pattern(url_pattern)
        if not is_valid:
            raise serializers.ValidationError(error_message)

        return url_pattern

    def validate_options(self, options):
        if not isinstance(options, dict):
            raise serializers.ValidationError("Options must be a JSON object.")
        return options

    def validate_name(self, name):
        if not self.instance or self.instance.name != name:
            # has_table covers system/posthog tables and warehouse objects the requesting user can see;
            # it's user-filtered, so also resolve the name team-wide using get_view_or_table_by_name.
            # Otherwise a user with denied table could create another one with colliding name.
            if self.context["database"].has_table(name) or get_view_or_table_by_name(self.context["team_id"], name):
                raise serializers.ValidationError("A table with this name already exists.")

        return name


class SimpleTableSerializer(UserAccessControlSerializerMixin, serializers.ModelSerializer):
    columns = serializers.SerializerMethodField(read_only=True)
    hogql_name = serializers.SerializerMethodField(
        read_only=True,
        help_text="Dotted name the table is queried by in HogQL (e.g. `googleanalytics.devices` or "
        "`postgres.<prefix>.<table>`), as opposed to `name`, which is the underlying storage identifier.",
    )

    class Meta:
        model = DataWarehouseTable
        fields = ["id", "name", "hogql_name", "columns", "row_count", "user_access_level"]
        read_only_fields = ["id", "name", "hogql_name", "columns", "row_count", "user_access_level"]

    @extend_schema_field(serializers.CharField())
    def get_hogql_name(self, table: DataWarehouseTable) -> str:
        return get_data_warehouse_table_name(table.external_data_source, table.name)

    def get_columns(self, table: DataWarehouseTable) -> list[SerializedField]:
        # Callers that don't consume columns (e.g. the source list) skip the expensive HogQL
        # field serialization entirely by passing include_columns=False.
        if not self.context.get("include_columns", True):
            return []

        database = self.context.get("database", None)
        team_id = self.context.get("team_id", None)

        if not database:
            request = self.context.get("request")
            database = Database.create_for(
                team_id=self.context["team_id"],
                user=cast(User, request.user) if request else None,
            )

        fields = serialize_fields(
            table.hogql_definition().fields,
            HogQLContext(database=database, team_id=team_id),
            table.name_chain,
            table_type="external",
        )
        return [
            SerializedField(
                key=field.name,
                name=field.name,
                type=field.type,
                schema_valid=field.schema_valid,
                fields=field.fields,
                table=field.table,
                chain=field.chain,
            )
            for field in fields
        ]


class FileUploadResponseSerializer(serializers.Serializer):
    upload_id = serializers.UUIDField(
        help_text="Id of the stored upload. Pass it to create_from_upload to build the table."
    )
    filename = serializers.CharField(help_text="Sanitized name the file was stored under.")
    file_format = serializers.CharField(help_text="Format the file will be read as: 'csv', 'json', or 'parquet'.")
    size_bytes = serializers.IntegerField(help_text="Size of the stored file in bytes.")


class CreateTableFromUploadSerializer(serializers.Serializer):
    upload_id = serializers.UUIDField(help_text="Id returned by upload_file for the stored file.")
    filename = serializers.CharField(help_text="Sanitized filename returned by upload_file.")
    file_format = serializers.ChoiceField(
        choices=SUPPORTED_FILE_FORMATS, help_text="How the uploaded file is read: 'csv', 'json', or 'parquet'."
    )
    table_name = serializers.CharField(help_text="Name the resulting table is queried by in HogQL.")

    def validate_table_name(self, table_name: str) -> str:
        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", table_name):
            raise serializers.ValidationError(
                "Table names must start with a letter or underscore and contain only alphanumeric characters or underscores."
            )
        return table_name


class TableViewSet(TeamAndOrgViewSetMixin, AccessControlViewSetMixin, viewsets.ModelViewSet):
    """
    Create, Read, Update and Delete Warehouse Tables.
    """

    scope_object = "warehouse_table"
    queryset = DataWarehouseTable.objects.all()
    serializer_class = TableSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["name"]
    ordering = "-created_at"

    def get_serializer_context(self) -> dict[str, Any]:
        context = super().get_serializer_context()
        # Building the HogQL database is only needed to serialize columns; a caller that opts out
        # (a picker that just needs table names) skips both the columns and the database build.
        include_columns = self.request.query_params.get("include_columns", "true").lower() != "false"
        context["include_columns"] = include_columns
        if include_columns:
            context["database"] = Database.create_for(team_id=self.team_id, user=cast(User, self.request.user))
        context["team_id"] = self.team_id
        return context

    def safely_get_queryset(self, queryset):
        return (
            queryset.filter(team_id=self.team_id)
            .exclude(deleted=True)
            .exclude(external_data_source__access_method=ExternalDataSource.AccessMethod.DIRECT)
            .prefetch_related("created_by", "externaldataschema_set")
            .order_by(self.ordering)
        )

    def destroy(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        instance: DataWarehouseTable = self.get_object()

        if instance.external_data_source is not None:
            return response.Response(
                status=status.HTTP_400_BAD_REQUEST, data={"message": "Can't delete a sourced table"}
            )

        instance.soft_delete()
        _delete_hosted_upload_file(instance)

        return response.Response(status=status.HTTP_204_NO_CONTENT)

    def perform_update(self, serializer):
        instance = serializer.instance
        validated_data = serializer.validated_data

        credential_data = validated_data.pop("credential", None)
        if credential_data:
            access_key = credential_data.get("access_key")
            access_secret = credential_data.get("access_secret")

            if access_key is not None and len(access_key.strip()) == 0:
                raise serializers.ValidationError("Access key can't be blank")
            if access_secret is not None and len(access_secret.strip()) == 0:
                raise serializers.ValidationError("Access secret can't be blank")

            credential = instance.credential
            if access_key is not None:
                credential.access_key = access_key
            if access_secret is not None:
                credential.access_secret = access_secret
            credential.save()

        old_csv_allow_double_quotes = instance.csv_allow_double_quotes
        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        if (
            instance._is_csv_format()
            and instance.csv_allow_double_quotes is not None
            and instance.csv_allow_double_quotes != old_csv_allow_double_quotes
        ):
            try:
                instance._validate_csv_double_quotes_setting()
            except Exception as err:
                raise serializers.ValidationError(str(err))

        try:
            instance.save()
        except Exception as err:
            raise serializers.ValidationError(str(err))

    @action(methods=["POST"], detail=True, required_scopes=["warehouse_table:write"])
    def update_schema(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        table: DataWarehouseTable = self.get_object()

        updates = request.data.get("updates", None)
        if updates is None:
            return response.Response(status=status.HTTP_200_OK)

        if table.external_data_source is not None:
            return response.Response(
                status=status.HTTP_400_BAD_REQUEST, data={"message": "The table must be a manually linked table"}
            )

        columns = table.columns or {}
        column_keys = list(columns.keys())
        for key in updates.keys():
            if key not in column_keys:
                return response.Response(
                    status=status.HTTP_400_BAD_REQUEST, data={"message": f"Column {key} does not exist on table"}
                )

        for key, value in updates.items():
            try:
                DatabaseSerializedFieldType[value.upper()]
            except:
                return response.Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": f"Can not parse type {value} for column {key} - type does not exist"},
                )

            current_value = columns[key]
            # If the column is in the "old" style, convert it to the new
            if isinstance(current_value, str):
                columns[key] = {}

            columns[key]["clickhouse"] = f"Nullable({SERIALIZED_FIELD_TO_CLICKHOUSE_MAPPING[value]})"
            columns[key]["hogql"] = CLICKHOUSE_HOGQL_MAPPING[SERIALIZED_FIELD_TO_CLICKHOUSE_MAPPING[value]].__name__

        table.columns = columns
        table.save()

        # Have to update the `valid` value separately to the `columns` value as the columns are required in the `ast.S3Table` class when querying ClickHouse
        user = cast(User, request.user)
        for key in updates.keys():
            columns[key]["valid"] = table.validate_column_type(key, user=user)

        table.columns = columns
        table.save()

        return response.Response(status=status.HTTP_200_OK)

    @extend_schema(
        request=None,
        responses={200: OpenApiResponse(description="Schema refreshed from the table's underlying source")},
        summary="Refresh table schema from source",
        description=(
            "Re-introspect a self-managed (manually linked) warehouse table's schema from its underlying "
            "source files and overwrite its stored column list. Use when the source schema has evolved "
            "(e.g. new columns in the underlying Delta/Parquet/CSV files) but queries still can't see the "
            "new columns, because PostHog serves a cached column snapshot until the table is refreshed. "
            "Not for tables managed by an external data source sync — those refresh on their own schedule."
        ),
    )
    @action(methods=["POST"], detail=True, required_scopes=["warehouse_table:write"])
    def refresh_schema(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        table: DataWarehouseTable = self.get_object()

        table.columns = table.get_columns()
        table.save()

        return response.Response(status=status.HTTP_200_OK)

    @extend_schema(
        request={
            "multipart/form-data": {
                "type": "object",
                "properties": {
                    "file": {"type": "string", "format": "binary", "description": "The file to upload."},
                    "file_format": {
                        "type": "string",
                        "enum": list(SUPPORTED_FILE_FORMATS),
                        "description": "How the file will be read when the table is created.",
                    },
                },
                "required": ["file", "file_format"],
            }
        },
        responses={201: FileUploadResponseSerializer},
        summary="Upload a file for a new self-managed warehouse table",
    )
    @action(
        methods=["POST"],
        detail=False,
        required_scopes=["warehouse_table:write"],
        parser_classes=[parsers.MultiPartParser, parsers.FormParser],
    )
    def upload_file(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        """Store an uploaded file in object storage so a self-managed table can be created from it.

        Uploading is a separate first step from `create_from_upload` so the create call stays JSON-only:
        this returns an `upload_id` the caller passes back to build the table. The file is written under
        a team-scoped prefix, so a table can only ever read back its own team's uploads.
        """
        if not settings.DATAWAREHOUSE_BUCKET:
            return response.Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "Object storage must be available to upload files."},
            )

        # Reject an oversized body up front, before accessing request.FILES triggers multipart parsing
        # and spools every part to disk. Reading only Content-Length here keeps the guard cheap.
        content_length = request.META.get("CONTENT_LENGTH")
        try:
            declared_body_size = int(content_length) if content_length else 0
        except (TypeError, ValueError):
            declared_body_size = 0
        if declared_body_size > MAX_UPLOAD_REQUEST_BODY_BYTES:
            return response.Response(
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                data={
                    "message": f"Upload exceeds the maximum of {MAX_FILE_UPLOAD_SIZE_BYTES // (1024 * 1024)}MB. "
                    "For larger files, connect the bucket they live in as a self-managed source instead."
                },
            )

        if "file" not in request.FILES:
            return response.Response(status=status.HTTP_400_BAD_REQUEST, data={"message": "No file provided"})

        # One upload per request: additional parts would already be spooled by the parser, but bounded
        # by the body cap above; rejecting keeps the endpoint's contract single-file and unambiguous.
        if len(request.FILES.getlist("file")) > 1 or len(request.FILES) > 1:
            return response.Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "Upload one file per request."},
            )

        file = request.FILES["file"]

        file_format = request.data.get("file_format")
        if file_format not in SUPPORTED_FILE_FORMATS:
            return response.Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": f"Invalid format. Must be one of: {', '.join(SUPPORTED_FILE_FORMATS)}"},
            )

        if file.size > MAX_FILE_UPLOAD_SIZE_BYTES:
            return response.Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={
                    "message": f"File size exceeds the maximum of {MAX_FILE_UPLOAD_SIZE_BYTES // (1024 * 1024)}MB. "
                    "For larger files, connect the bucket they live in as a self-managed source instead."
                },
            )

        # Django strips path separators via os.path.basename in UploadedFile._set_name; restricting
        # further to safe characters is defense-in-depth for the S3 key.
        safe_filename = re.sub(r"[^a-zA-Z0-9._-]", "_", file.name or "")
        if not safe_filename or safe_filename.startswith("."):
            return response.Response(status=status.HTTP_400_BAD_REQUEST, data={"message": "Invalid filename"})

        upload_id = uuid.uuid4()
        path = build_file_upload_s3_path(self.team_id, str(upload_id), safe_filename)

        try:
            s3 = get_s3_client()
            with s3.open(path, "wb") as destination:
                for chunk in file.chunks():
                    destination.write(chunk)
        except Exception as e:
            capture_exception(e)
            return response.Response(status=status.HTTP_400_BAD_REQUEST, data={"message": "Failed to upload file"})

        return response.Response(
            status=status.HTTP_201_CREATED,
            data=FileUploadResponseSerializer(
                {
                    "upload_id": upload_id,
                    "filename": safe_filename,
                    "file_format": file_format,
                    "size_bytes": file.size,
                }
            ).data,
        )

    @extend_schema(
        request=CreateTableFromUploadSerializer,
        responses={201: TableSerializer},
        summary="Create a self-managed warehouse table from an uploaded file",
    )
    @action(methods=["POST"], detail=False, required_scopes=["warehouse_table:write"])
    def create_from_upload(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        """Turn a previously uploaded file into a self-managed warehouse table.

        The file already sits in PostHog's own bucket (see `upload_file`), so the table points straight
        at it and is read in place — no import pipeline and no recurring sync, the same shape as a linked
        S3/GCS bucket. The read location is always derived from the caller's own team, so a client-supplied
        `upload_id` can only resolve inside that team's folder, and the table carries no credential (reads
        fall back to the node role, never a user-supplied key).
        """
        # Both settings back the table: the bucket resolves the S3 read path, the domain builds the
        # queryable url_pattern. Missing either would create a table whose every query fails.
        if not settings.DATAWAREHOUSE_BUCKET or not settings.DATAWAREHOUSE_BUCKET_DOMAIN:
            return response.Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "Object storage must be available to create a table from a file."},
            )

        serializer = CreateTableFromUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        upload_id = str(serializer.validated_data["upload_id"])
        filename = serializer.validated_data["filename"]
        file_format = serializer.validated_data["file_format"]
        table_name = serializer.validated_data["table_name"]

        # Reject duplicate names up front, the same way TableSerializer.validate_name does — has_table
        # is user-filtered, so also resolve team-wide to stop a denied table being shadowed by a new one.
        database = Database.create_for(team_id=self.team_id, user=cast(User, request.user))
        if database.has_table(table_name) or get_view_or_table_by_name(self.team_id, table_name):
            return response.Response(
                status=status.HTTP_400_BAD_REQUEST, data={"message": "A table with this name already exists."}
            )

        # Confirm the object is actually there before creating a table that would fail every query.
        upload_path = build_file_upload_s3_path(self.team_id, upload_id, filename)
        try:
            if not get_s3_client().exists(upload_path):
                return response.Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": "Uploaded file not found. Please upload the file again."},
                )
        except Exception as e:
            capture_exception(e)
            return response.Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "Could not verify the uploaded file. Please try uploading it again."},
            )

        table = DataWarehouseTable(
            team_id=self.team_id,
            name=table_name,
            format=FILE_FORMAT_TO_TABLE_FORMAT[file_format],
            url_pattern=build_file_upload_url_pattern(self.team_id, upload_id, filename),
            created_by=request.user if isinstance(request.user, User) else None,
        )
        try:
            table.columns = table.get_columns()
        except Exception as err:
            return response.Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": f"Could not read columns from the uploaded file: {err}"},
            )
        table.save()

        validate_data_warehouse_table_columns.delay(self.team_id, str(table.id))

        return response.Response(
            status=status.HTTP_201_CREATED,
            data=TableSerializer(table, context=self.get_serializer_context()).data,
        )

    @action(
        methods=["POST"],
        detail=False,
        required_scopes=["warehouse_table:write"],
        parser_classes=[parsers.MultiPartParser, parsers.FormParser],
    )
    def file(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        team = Team.objects.get(id=self.team_id)
        is_warehouse_api_enabled = posthoganalytics.feature_enabled(
            "warehouse-api",
            str(team.organization_id),
            groups={"organization": str(team.organization_id)},
            group_properties={"organization": {"id": str(team.organization_id)}},
        )

        if not is_warehouse_api_enabled:
            return response.Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "Warehouse API is not enabled for this organization"},
            )

        if "file" not in request.FILES:
            return response.Response(status=status.HTTP_400_BAD_REQUEST, data={"message": "No file provided"})

        file = request.FILES["file"]

        # Sanitize filename — Django strips path separators via os.path.basename
        # in UploadedFile._set_name, but we further restrict to safe characters
        # as defense-in-depth for the S3 key and url_pattern.
        safe_filename = re.sub(r"[^a-zA-Z0-9._-]", "_", file.name)
        if not safe_filename or safe_filename.startswith("."):
            return response.Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": "Invalid filename"},
            )

        table_name = request.data.get("name", safe_filename)
        file_format = request.data.get("format", "CSVWithNames")

        # Validate format against allowed choices
        valid_formats = {c[0] for c in DataWarehouseTable.TableFormat.choices}
        if file_format not in valid_formats:
            return response.Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": f"Invalid format. Must be one of: {', '.join(sorted(valid_formats))}"},
            )

        # Validate table name format
        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", table_name):
            return response.Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={
                    "message": "Table names must start with a letter or underscore and contain only alphanumeric characters or underscores."
                },
            )

        # Validate table name
        team_id = self.team_id
        table = None
        table_query = DataWarehouseTable.objects.exclude(deleted=True).filter(team_id=team_id, name=table_name)
        if table_query.exists():
            table = table_query.first()

        if file.size > 52428800:  # 50MB in bytes
            return response.Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"message": f"File size exceeds maximum allowed size of 50MB"},
            )

        # Create the table record
        try:
            # Create the table if it doesn't exist, otherwise use existing one
            if table is None:
                created_by = request.user if isinstance(request.user, User) else None
                table = DataWarehouseTable.objects.create(
                    team_id=team_id,
                    name=table_name,
                    format=file_format,
                    created_by=created_by,
                )

            # Generate URL pattern and store file in object storage
            if settings.DATAWAREHOUSE_BUCKET:
                if settings.USE_LOCAL_SETUP:
                    s3 = boto3.client(
                        "s3",
                        aws_access_key_id=settings.DATAWAREHOUSE_LOCAL_ACCESS_KEY,
                        aws_secret_access_key=settings.DATAWAREHOUSE_LOCAL_ACCESS_SECRET,
                        endpoint_url=settings.OBJECT_STORAGE_ENDPOINT,
                    )
                else:
                    s3 = boto3.client("s3")

                s3.upload_fileobj(file, settings.DATAWAREHOUSE_BUCKET, f"managed/team_{team_id}/{safe_filename}")

                # Set the URL pattern for the table
                table.url_pattern = (
                    f"https://{settings.DATAWAREHOUSE_BUCKET_DOMAIN}/managed/team_{team_id}/{safe_filename}"
                )
                table.format = file_format

                # Try to determine columns from the file
                table.columns = table.get_columns()
                table.save()

                # Validate columns in background
                from posthog.tasks.warehouse import validate_data_warehouse_table_columns

                validate_data_warehouse_table_columns.delay(team_id, str(table.id))

                return response.Response(
                    status=status.HTTP_201_CREATED,
                    data=TableSerializer(table, context=self.get_serializer_context()).data,
                )
            else:
                if table is not None and table.credential is None:
                    table.delete()
                return response.Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"message": "Object storage must be available to upload files."},
                )
        except Exception as e:
            capture_exception(e)
            return response.Response(status=status.HTTP_400_BAD_REQUEST, data={"message": "Failed to upload file"})
