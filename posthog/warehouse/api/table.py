import re
from typing import Any

from django.conf import settings

import boto3
import posthoganalytics
from rest_framework import filters, parsers, request, response, serializers, status, viewsets

from posthog.schema import DatabaseSerializedFieldType

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database, SerializedField, serialize_fields

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import action
from posthog.exceptions_capture import capture_exception
from posthog.models import Team
from posthog.tasks.warehouse import validate_data_warehouse_table_columns
from posthog.warehouse.api.external_data_source import SimpleExternalDataSourceSerializers
from posthog.warehouse.models import DataWarehouseCredential, DataWarehouseTable
from posthog.warehouse.models.credential import get_or_create_datawarehouse_credential
from posthog.warehouse.models.table import CLICKHOUSE_HOGQL_MAPPING, SERIALIZED_FIELD_TO_CLICKHOUSE_MAPPING


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


class TableSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    credential = CredentialSerializer()
    columns = serializers.SerializerMethodField(read_only=True)
    external_data_source = SimpleExternalDataSourceSerializers(read_only=True)
    external_schema = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = DataWarehouseTable
        fields = [
            "id",
            "deleted",
            "name",
            "format",
            "created_by",
            "created_at",
            "url_pattern",
            "credential",
            "columns",
            "external_data_source",
            "external_schema",
        ]
        read_only_fields = ["id", "created_by", "created_at", "columns", "external_data_source", "external_schema"]

    def get_columns(self, table: DataWarehouseTable) -> list[SerializedField]:
        database = self.context.get("database", None)
        if not database:
            database = Database.create_for(team_id=self.context["team_id"])

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

    def get_external_schema(self, instance: DataWarehouseTable):
        from posthog.warehouse.api.external_data_schema import SimpleExternalDataSchemaSerializer

        return SimpleExternalDataSchemaSerializer(instance.externaldataschema_set.first(), read_only=True).data or None

    def create(self, validated_data):
        team_id = self.context["team_id"]

        validated_data["team_id"] = team_id
        validated_data["created_by"] = self.context["request"].user
        if validated_data.get("credential"):
            validated_data["credential"] = DataWarehouseCredential.objects.create(
                team_id=team_id,
                access_key=validated_data["credential"]["access_key"],
                access_secret=validated_data["credential"]["access_secret"],
            )
        table = DataWarehouseTable(**validated_data)
        try:
            table.columns = table.get_columns()
        except Exception as err:
            raise serializers.ValidationError(str(err))
        table.save()

        validate_data_warehouse_table_columns.delay(self.context["team_id"], str(table.id))

        return table

    def validate_name(self, name):
        if not self.instance or self.instance.name != name:
            name_exists_in_hogql_database = self.context["database"].has_table(name)
            if name_exists_in_hogql_database:
                raise serializers.ValidationError("A table with this name already exists.")

        return name


class SimpleTableSerializer(serializers.ModelSerializer):
    columns = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = DataWarehouseTable
        fields = ["id", "name", "columns", "row_count"]
        read_only_fields = ["id", "name", "columns", "row_count"]

    def get_columns(self, table: DataWarehouseTable) -> list[SerializedField]:
        database = self.context.get("database", None)
        team_id = self.context.get("team_id", None)

        if not database:
            database = Database.create_for(team_id=self.context["team_id"])

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


class TableViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
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
        context["database"] = Database.create_for(team_id=self.team_id)
        context["team_id"] = self.team_id
        return context

    def safely_get_queryset(self, queryset):
        return (
            queryset.filter(team_id=self.team_id)
            .exclude(deleted=True)
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

        return response.Response(status=status.HTTP_204_NO_CONTENT)

    def perform_update(self, serializer):
        instance = serializer.instance
        validated_data = serializer.validated_data

        credential_data = validated_data.pop("credential", None)
        if credential_data:
            credential = instance.credential
            credential.access_key = credential_data.get("access_key", credential.access_key)
            credential.access_secret = credential_data.get("access_secret", credential.access_secret)
            credential.save()

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

    @action(methods=["POST"], detail=True)
    def update_schema(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        updates = request.data.get("updates", None)
        if updates is None:
            return response.Response(status=status.HTTP_200_OK)

        table: DataWarehouseTable = self.get_object()
        if table.external_data_source is not None:
            return response.Response(
                status=status.HTTP_400_BAD_REQUEST, data={"message": "The table must be a manually linked table"}
            )

        columns = table.columns
        column_keys: list[str] = columns.keys()
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
        for key in updates.keys():
            columns[key]["valid"] = table.validate_column_type(key)

        table.columns = columns
        table.save()

        return response.Response(status=status.HTTP_200_OK)

    @action(methods=["POST"], detail=True)
    def refresh_schema(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        table: DataWarehouseTable = self.get_object()

        table.columns = table.get_columns()
        table.save()

        return response.Response(status=status.HTTP_200_OK)

    @action(methods=["POST"], detail=False)
    def sync_status(self, request: request.Request, *args: Any, **kwargs: Any) -> response.Response:
        """Check sync status for multiple data warehouse tables."""
        from posthog.warehouse.models import ExternalDataSchema

        table_names = request.data.get("table_names", [])
        if not isinstance(table_names, list):
            return response.Response(status=status.HTTP_400_BAD_REQUEST, data={"message": "table_names must be a list"})

        tables_with_issues = []
        for table_name in table_names:
            try:
                table = (
                    DataWarehouseTable.objects.filter(team_id=self.team_id, name=table_name, deleted=False)
                    .select_related("external_data_source")
                    .first()
                )

                if not table or not table.external_data_source:
                    continue

                schemas = ExternalDataSchema.objects.filter(table=table, deleted=False).select_related("source")

                for schema in schemas:
                    if not schema.should_sync:
                        tables_with_issues.append(
                            {
                                "table_name": table_name,
                                "status": "disabled",
                                "message": f"Sync for table '{table_name}' is disabled",
                                "schema_id": str(schema.id),
                            }
                        )
                    elif schema.status == ExternalDataSchema.Status.FAILED:
                        tables_with_issues.append(
                            {
                                "table_name": table_name,
                                "status": "failed",
                                "message": f"Sync for table '{table_name}' has failed",
                                "error": schema.latest_error,
                                "schema_id": str(schema.id),
                            }
                        )
                    elif schema.status == ExternalDataSchema.Status.PAUSED:
                        tables_with_issues.append(
                            {
                                "table_name": table_name,
                                "status": "paused",
                                "message": f"Sync for table '{table_name}' is paused",
                                "schema_id": str(schema.id),
                            }
                        )

            except Exception:
                continue

        return response.Response(status=status.HTTP_200_OK, data=tables_with_issues)

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
        table_name = request.data.get("name", file.name)
        file_format = request.data.get("format", "CSVWithNames")

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
            # Create credential if object storage is available
            credential = None
            if hasattr(settings, "AIRBYTE_BUCKET_KEY") and hasattr(settings, "AIRBYTE_BUCKET_SECRET"):
                credential = get_or_create_datawarehouse_credential(
                    team_id=team_id,
                    access_key=settings.AIRBYTE_BUCKET_KEY,
                    access_secret=settings.AIRBYTE_BUCKET_SECRET,
                )
            else:
                capture_exception(
                    Exception("Object storage keys not found: AIRBYTE_BUCKET_KEY or AIRBYTE_BUCKET_SECRET")
                )
                return response.Response(
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    data={"message": "An unexpected error occurred. Please try again later."},
                )

            # Create the table if it doesn't exist, otherwise use existing one
            if table is None:
                table = DataWarehouseTable.objects.create(
                    team_id=team_id,
                    name=table_name,
                    format=file_format,
                    created_by=request.user,
                    credential=credential,  # type: ignore
                )

            # Generate URL pattern and store file in object storage
            if credential and settings.DATAWAREHOUSE_BUCKET:
                s3 = boto3.client(
                    "s3",
                    aws_access_key_id=credential.access_key,
                    aws_secret_access_key=credential.access_secret,
                    endpoint_url=settings.OBJECT_STORAGE_ENDPOINT,
                )
                s3.upload_fileobj(file, settings.DATAWAREHOUSE_BUCKET, f"managed/team_{team_id}/{file.name}")

                # Set the URL pattern for the table
                table.url_pattern = f"https://{settings.AIRBYTE_BUCKET_DOMAIN}/managed/team_{team_id}/{file.name}"
                table.format = file_format

                if table.credential is None:
                    table.credential = credential

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
