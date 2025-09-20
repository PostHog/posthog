import typing
import datetime as dt
import operator
import collections.abc

from django.conf import settings

import pyarrow as pa
from dlt.common.normalizers.naming.snake_case import NamingConvention
from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.v19.common import types as ga_common
from google.ads.googleads.v19.enums import types as ga_enums
from google.ads.googleads.v19.resources import types as ga_resources
from google.ads.googleads.v19.services import types as ga_services
from google.oauth2 import service_account
from google.protobuf.json_format import MessageToJson

from posthog.models.integration import Integration
from posthog.temporal.data_imports.pipelines.helpers import incremental_type_to_initial_value
from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from posthog.temporal.data_imports.sources.common import config
from posthog.temporal.data_imports.sources.common.sql import Column, Table
from posthog.temporal.data_imports.sources.generated_configs import GoogleAdsSourceConfig
from posthog.temporal.data_imports.sources.google_ads.schemas import RESOURCE_SCHEMAS
from posthog.warehouse.types import IncrementalFieldType


def _clean_customer_id(s: str | None) -> str | None:
    """Clean customer IDs from Google Ads.

    Customer IDs can contain dashes, but we need the ID without them.
    """
    if not s:
        return s

    return s.strip().replace("-", "")


@config.config
class GoogleAdsServiceAccountSourceConfig(config.Config):
    """Google Ads source config using service account for authentication.

    Old config for when we were using a service account instead of oauth.
    ~100 sources still use this method for auth. We recommend using
    `GoogleAdsSourceConfig` instead"""

    customer_id: str = config.value(converter=_clean_customer_id)

    private_key: str = config.value(
        default_factory=config.default_from_settings("GOOGLE_ADS_SERVICE_ACCOUNT_PRIVATE_KEY")
    )
    private_key_id: str = config.value(
        default_factory=config.default_from_settings("GOOGLE_ADS_SERVICE_ACCOUNT_PRIVATE_KEY_ID")
    )
    client_email: str = config.value(
        default_factory=config.default_from_settings("GOOGLE_ADS_SERVICE_ACCOUNT_CLIENT_EMAIL")
    )
    token_uri: str = config.value(default_factory=config.default_from_settings("GOOGLE_ADS_SERVICE_ACCOUNT_TOKEN_URI"))
    developer_token: str = config.value(default_factory=config.default_from_settings("GOOGLE_ADS_DEVELOPER_TOKEN"))


GoogleAdsSourceConfigUnion = GoogleAdsServiceAccountSourceConfig | GoogleAdsSourceConfig


def google_ads_client(config: GoogleAdsSourceConfigUnion, team_id: int) -> GoogleAdsClient:
    """Initialize a `GoogleAdsClient` with provided config."""
    if isinstance(config, GoogleAdsSourceConfig):
        integration = Integration.objects.get(id=config.google_ads_integration_id, team_id=team_id)

        login_customer_id: str | None = None
        if config.is_mcc_account and config.is_mcc_account.enabled:
            login_customer_id = config.is_mcc_account.mcc_client_id

        client = GoogleAdsClient.load_from_dict(
            {
                "developer_token": settings.GOOGLE_ADS_DEVELOPER_TOKEN,
                "refresh_token": integration.refresh_token,
                "client_id": settings.GOOGLE_ADS_APP_CLIENT_ID,
                "client_secret": settings.GOOGLE_ADS_APP_CLIENT_SECRET,
                "use_proto_plus": False,
                "login_customer_id": login_customer_id,
            }
        )
    else:
        credentials = service_account.Credentials.from_service_account_info(
            {
                "private_key": config.private_key,
                "private_key_id": config.private_key_id,
                "token_uri": config.token_uri,
                "client_email": config.client_email,
            },
            scopes=["https://www.googleapis.com/auth/adwords"],
        )
        client = GoogleAdsClient(credentials=credentials, developer_token=config.developer_token)
    return client


class GoogleAdsColumn(Column):
    """Represents a column of a Google Ads resource."""

    def __init__(
        self,
        qualified_name: str,
        data_type: ga_enums.GoogleAdsFieldDataTypeEnum.GoogleAdsFieldDataType,
        is_repeatable: bool,
        type_url: str,
    ):
        self.name = qualified_name.replace(".", "_")
        self.qualified_name = qualified_name
        self.data_type = data_type
        self.type_url = type_url
        # Some types require special handling, so we provide quick access to them
        self.is_repeatable = is_repeatable
        self.is_enum = data_type == ga_enums.GoogleAdsFieldDataTypeEnum.GoogleAdsFieldDataType.ENUM
        self.is_message = data_type == ga_enums.GoogleAdsFieldDataTypeEnum.GoogleAdsFieldDataType.MESSAGE
        self.is_date = data_type == ga_enums.GoogleAdsFieldDataTypeEnum.GoogleAdsFieldDataType.DATE

    def to_arrow_field(self):
        """Return the Arrow type associated with this column.

        Special handling for:
          * ENUM: We cast them to `str`.
          * MESSAGE: Serialized as JSON strings.
        """
        arrow_type: pa.DataType

        match self.data_type:
            case ga_enums.GoogleAdsFieldDataTypeEnum.GoogleAdsFieldDataType.BOOLEAN:
                arrow_type = pa.bool_()
            case ga_enums.GoogleAdsFieldDataTypeEnum.GoogleAdsFieldDataType.DATE:
                arrow_type = pa.date32()
            case ga_enums.GoogleAdsFieldDataTypeEnum.GoogleAdsFieldDataType.DOUBLE:
                arrow_type = pa.float64()
            case ga_enums.GoogleAdsFieldDataTypeEnum.GoogleAdsFieldDataType.ENUM:
                arrow_type = pa.string()
            case ga_enums.GoogleAdsFieldDataTypeEnum.GoogleAdsFieldDataType.FLOAT:
                arrow_type = pa.float64()
            case ga_enums.GoogleAdsFieldDataTypeEnum.GoogleAdsFieldDataType.INT32:
                arrow_type = pa.int32()
            case ga_enums.GoogleAdsFieldDataTypeEnum.GoogleAdsFieldDataType.INT64:
                arrow_type = pa.int64()
            case ga_enums.GoogleAdsFieldDataTypeEnum.GoogleAdsFieldDataType.MESSAGE:
                # Message types could be treated as Arrow structs, as they are well defined.
                # But doing so requires introspecting into Protobuf message types and resolving
                # any type inconsistencies.
                # For simplicity, we will store these as JSON strings.
                # TODO: Maybe use arrow structs later?
                arrow_type = pa.string()
            case (
                ga_enums.GoogleAdsFieldDataTypeEnum.GoogleAdsFieldDataType.RESOURCE_NAME
                | ga_enums.GoogleAdsFieldDataTypeEnum.GoogleAdsFieldDataType.STRING
            ):
                arrow_type = pa.string()
            case ga_enums.GoogleAdsFieldDataTypeEnum.GoogleAdsFieldDataType.UINT64:
                arrow_type = pa.uint64()
            case _:
                raise ValueError(f"Column '{self.name}' has an unsupported protobuf type: '{self.data_type}'")

        if self.is_repeatable:
            arrow_type = pa.list_(arrow_type)

        return pa.field(self.name, arrow_type)


def _resolve_protobuf_message_type_url(type_url: str) -> type:
    """Traverse a protobuf message type URL to find it's Python type."""
    match type_url.split("."):
        case (
            ["google", "ads", "googleads", "v19", "common", *rest]
            | ["com", "google", "ads", "googleads", "v19", "common", *rest]
        ):
            return _traverse_attributes(ga_common, *rest)
        case (
            ["google", "ads", "googleads", "v19", "enums", *rest]
            | ["com", "google", "ads", "googleads", "v19", "enums", *rest]
        ):
            return _traverse_attributes(ga_enums, *rest)
        case (
            ["google", "ads", "googleads", "v19", "resources", *rest]
            | ["com", "google", "ads", "googleads", "v19", "resources", *rest]
        ):
            return _traverse_attributes(ga_resources, *rest)
        case _:
            raise ValueError(f"Type url could not be found: '{type_url}'")


def _traverse_attributes(thing: typing.Any, *path: str):
    """Attempt to traverse attributes of thing."""
    current = thing

    for component in path:
        if component == "type":
            component += "_"

        current = getattr(current, component)
    return current


def get_incremental_fields() -> dict[str, list[tuple[str, IncrementalFieldType]]]:
    d = {}
    for alias, contents in RESOURCE_SCHEMAS.items():
        assert isinstance(contents, dict)

        if "filter_field_names" not in contents:
            continue

        d[alias] = contents["filter_field_names"]

    return d


class GoogleAdsTable(Table[GoogleAdsColumn]):
    def __init__(self, *args, requires_filter: bool, primary_key: list[str], **kwargs):
        self.requires_filter = requires_filter
        self.primary_key = [pkey.replace(".", "_") for pkey in primary_key]
        super().__init__(*args, **kwargs)


TableSchemas = dict[str, GoogleAdsTable]


def get_schemas(config: GoogleAdsSourceConfigUnion, team_id: int) -> TableSchemas:
    """Obtain Google Ads schemas.

    This is a two step process:
    1. Query all Google Ads resources resources.
    2. Query the fields for said resources.

    Only selectable fields are, well, selected.
    """
    client = google_ads_client(config, team_id)
    gaf_service = client.get_service("GoogleAdsFieldService")
    fields_query = gaf_service.search_google_ads_fields(
        query=f"select name, data_type, is_repeated, type_url where selectable = true"
    )
    fields_map = {field.name: field for field in fields_query.results}
    table_schemas = {}

    for table_alias, resource_contents in RESOURCE_SCHEMAS.items():
        assert isinstance(resource_contents, dict)

        resource_name = resource_contents["resource_name"]
        assert isinstance(resource_name, str)

        field_names = resource_contents["field_names"]

        requires_filter = resource_contents.get("filter_field_names", None) is not None
        primary_key = typing.cast(list[str], resource_contents.get("primary_key", []))

        columns = []

        for field_name in field_names:
            assert isinstance(field_name, str)

            try:
                field = fields_map[field_name]
            except KeyError:
                field = fields_map[field_name.removeprefix(f"{resource_name}.")]

            columns.append(
                GoogleAdsColumn(
                    qualified_name=field_name,
                    data_type=field.data_type,
                    is_repeatable=field.is_repeated,
                    type_url=field.type_url,
                )
            )

        table = GoogleAdsTable(
            name=resource_name,
            alias=table_alias,
            requires_filter=requires_filter,
            primary_key=primary_key,
            columns=columns,
            parents=None,
        )
        table_schemas[table_alias] = table

    return table_schemas


def google_ads_source(
    config: GoogleAdsSourceConfigUnion,
    resource_name: str,
    team_id: int,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: typing.Any = None,
    incremental_field: str | None = None,
    incremental_field_type: IncrementalFieldType | None = None,
) -> SourceResponse:
    """A data warehouse Google Ads source.

    We utilize the Google Ads gRPC API to query for the configured resource and
    yield batches of rows as `pyarrow.Table`.
    """

    name = NamingConvention().normalize_identifier(resource_name)
    table = get_schemas(config, team_id)[resource_name]

    if table.requires_filter and not should_use_incremental_field:
        should_use_incremental_field = True
        incremental_field = "segments.date"
        incremental_field_type = IncrementalFieldType.Date

    def get_rows() -> collections.abc.Iterator[pa.Table]:
        query = f"SELECT {','.join(f'{field.qualified_name}' for field in table)} FROM {table.name}"

        if should_use_incremental_field:
            if incremental_field is None or incremental_field_type is None:
                raise ValueError("incremental_field and incremental_field_type can't be None")

            if db_incremental_field_last_value is None:
                last_value: int | dt.datetime | dt.date | str = incremental_type_to_initial_value(
                    incremental_field_type
                )
            else:
                last_value = db_incremental_field_last_value

            if isinstance(last_value, dt.datetime) or isinstance(last_value, dt.date):
                last_value = f"'{last_value.isoformat()}'"

            query += f" WHERE {incremental_field} >= {last_value}"

            if incremental_field_type == IncrementalFieldType.Date:
                # Dates require an upper bound too, so we pick something very in the future.
                # TODO: Make sure to bump this before 2100-01-01.
                query += f" AND {incremental_field} < '2100-01-01'"

        client = google_ads_client(config, team_id)
        service = client.get_service("GoogleAdsService", version="v19")
        stream = service.search_stream(query=query, customer_id=_clean_customer_id(config.customer_id))

        yield from _stream_as_arrow_table(stream, table)

    return SourceResponse(
        name=name,
        items=get_rows(),
        primary_keys=table.primary_key,
        partition_count=1 if table.requires_filter else None,  # this enables partitioning
        partition_size=1 if table.requires_filter else None,  # this enables partitioning
        partition_mode="datetime" if table.requires_filter else None,
        partition_format="day" if table.requires_filter else None,
        partition_keys=["segments_date"] if table.requires_filter else None,
    )


def _stream_as_arrow_table(
    stream: collections.abc.Iterable[ga_services.SearchGoogleAdsStreamResponse],
    table: Table[GoogleAdsColumn],
    table_size: int | None = None,
) -> collections.abc.Generator[pa.Table, None, None]:
    """Stream response batches as `pyarrow.Table`."""
    rows = []

    for batch in stream:
        for dict_row in _stream_response_as_dicts(batch, table):
            rows.append(dict_row)

            if table_size is not None and len(rows) >= table_size:
                yield pa.Table.from_pylist(rows, schema=table.to_arrow_schema())
                rows = []

        if table_size is None:
            yield pa.Table.from_pylist(rows, schema=table.to_arrow_schema())
            rows = []

    if len(rows) > 0:
        yield pa.Table.from_pylist(rows, schema=table.to_arrow_schema())


def _stream_response_as_dicts(
    response: ga_services.SearchGoogleAdsStreamResponse,
    table: Table[GoogleAdsColumn],
) -> collections.abc.Iterable[dict[str, typing.Any]]:
    """Stream response as dictionaries.

    Each row from a search stream query is packaged into a single GoogleAdsRow,
    regardless of underlying resource. This object will have a field set for the
    resource we are querying, and everything else unset.
    """
    field_paths = response.field_mask.paths
    get_enum_name = operator.attrgetter("name")

    for row in response.results:
        row_dict = {}

        for path in field_paths:
            value = _traverse_attributes(row, *path.split("."))
            column = table[path.replace(".", "_")]

            # TODO: Special type handling moved somewhere else.
            if column.is_enum:
                enum_cls = _resolve_protobuf_message_type_url(column.type_url)
                if column.is_repeatable:
                    value = list(map(get_enum_name, map(enum_cls, value)))
                else:
                    value = enum_cls(value).name

            elif column.is_message:
                if column.is_repeatable:
                    value = list(map(MessageToJson, value))
                else:
                    value = MessageToJson(value)

            elif column.is_date:
                if column.is_repeatable:
                    value = list(map(dt.date.fromisoformat, value))
                else:
                    value = dt.date.fromisoformat(value)

            row_dict[column.name] = value

        yield row_dict
