from typing import Any, Callable, Dict, List

from pydantic import BaseModel, Extra


class DatabaseField(BaseModel):
    """Base class for a field in a database table."""

    class Config:
        extra = Extra.forbid

    name: str
    array: bool = False


class IntegerDatabaseField(DatabaseField):
    pass


class StringDatabaseField(DatabaseField):
    pass


class StringJSONDatabaseField(DatabaseField):
    pass


class DateTimeDatabaseField(DatabaseField):
    pass


class BooleanDatabaseField(DatabaseField):
    pass


class Table(BaseModel):
    class Config:
        extra = Extra.forbid

    def has_field(self, name: str) -> bool:
        return hasattr(self, name)

    def get_field(self, name: str) -> DatabaseField:
        if self.has_field(name):
            return getattr(self, name)
        raise ValueError(f'Field "{name}" not found on table {self.__class__.__name__}')

    def clickhouse_table(self):
        raise NotImplementedError("Table.clickhouse_table not overridden")

    def get_splash(self) -> Dict[str, DatabaseField]:
        splash: Dict[str, DatabaseField] = {}
        for key, field in self.__fields__.items():
            database_field = field.default
            if key == "team_id":
                pass  # skip team_id
            elif isinstance(database_field, DatabaseField):
                splash[key] = database_field
            elif isinstance(database_field, Table) or isinstance(database_field, JoinedTable):
                pass  # ignore virtual tables for now
            else:
                raise ValueError(f"Unknown field type {type(database_field).__name__} for splash")
        return splash


class JoinedTable(BaseModel):
    class Config:
        extra = Extra.forbid

    join_function: Callable[[str, str, List[str]], Any]
    table: Table


class PersonsTable(Table):
    id: StringDatabaseField = StringDatabaseField(name="id")
    created_at: DateTimeDatabaseField = DateTimeDatabaseField(name="created_at")
    team_id: IntegerDatabaseField = IntegerDatabaseField(name="team_id")
    properties: StringJSONDatabaseField = StringJSONDatabaseField(name="properties")
    is_identified: BooleanDatabaseField = BooleanDatabaseField(name="is_identified")
    is_deleted: BooleanDatabaseField = BooleanDatabaseField(name="is_deleted")
    version: IntegerDatabaseField = IntegerDatabaseField(name="version")

    def clickhouse_table(self):
        return "person"


class PersonDistinctIdTable(Table):
    team_id: IntegerDatabaseField = IntegerDatabaseField(name="team_id")
    distinct_id: StringDatabaseField = StringDatabaseField(name="distinct_id")
    person_id: StringDatabaseField = StringDatabaseField(name="person_id")
    is_deleted: BooleanDatabaseField = BooleanDatabaseField(name="is_deleted")
    version: IntegerDatabaseField = IntegerDatabaseField(name="version")

    def get_splash(self) -> Dict[str, DatabaseField]:
        splash: Dict[str, DatabaseField] = {}
        for key, value in super().get_splash().items():
            if key != "is_deleted" and key != "version":
                splash[key] = value
        return splash

    def clickhouse_table(self):
        return "person_distinct_id2"


class EventsPersonSubTable(Table):
    id: StringDatabaseField = StringDatabaseField(name="person_id")
    created_at: DateTimeDatabaseField = DateTimeDatabaseField(name="person_created_at")
    properties: StringJSONDatabaseField = StringJSONDatabaseField(name="person_properties")

    def clickhouse_table(self):
        # This is a bit of a hack to make sure person.properties.x works
        return "events"


def join_with_max_person_distinct_id_table(base_table_alias: str, pdi_alias: str, requested_fields: List[str]):
    from posthog.hogql import ast

    if not requested_fields:
        requested_fields = ["person_id"]

    # contains the list of fields we will select from this table
    fields_to_select: List[ast.Expr] = []

    max_version: Callable[[ast.Expr], ast.Expr] = lambda field: ast.Call(
        name="argMax", args=[field, ast.Field(chain=["version"])]
    )
    for field in requested_fields:
        if field != "distinct_id":
            fields_to_select.append(ast.Alias(alias=field, expr=max_version(ast.Field(chain=[field]))))

    distinct_id = ast.Field(chain=["distinct_id"])

    return ast.JoinExpr(
        join_type="INNER JOIN",
        table=ast.SelectQuery(
            select=fields_to_select + [distinct_id],
            select_from=ast.JoinExpr(table=ast.Field(chain=["person_distinct_ids"])),
            group_by=[distinct_id],
            having=ast.CompareOperation(
                op=ast.CompareOperationType.Eq,
                left=max_version(ast.Field(chain=["is_deleted"])),
                right=ast.Constant(value=0),
            ),
        ),
        alias=pdi_alias,
        constraint=ast.CompareOperation(
            op=ast.CompareOperationType.Eq,
            left=ast.Field(chain=[base_table_alias, "distinct_id"]),
            right=ast.Field(chain=[pdi_alias, "distinct_id"]),
        ),
    )


class EventsTable(Table):
    uuid: StringDatabaseField = StringDatabaseField(name="uuid")
    event: StringDatabaseField = StringDatabaseField(name="event")
    properties: StringJSONDatabaseField = StringJSONDatabaseField(name="properties")
    timestamp: DateTimeDatabaseField = DateTimeDatabaseField(name="timestamp")
    team_id: IntegerDatabaseField = IntegerDatabaseField(name="team_id")
    distinct_id: StringDatabaseField = StringDatabaseField(name="distinct_id")
    elements_chain: StringDatabaseField = StringDatabaseField(name="elements_chain")
    created_at: DateTimeDatabaseField = DateTimeDatabaseField(name="created_at")
    person: EventsPersonSubTable = EventsPersonSubTable()

    pdi: JoinedTable = JoinedTable(table=PersonDistinctIdTable(), join_function=join_with_max_person_distinct_id_table)

    def clickhouse_table(self):
        return "events"


class SessionRecordingEvents(Table):
    uuid: StringDatabaseField = StringDatabaseField(name="uuid")
    timestamp: DateTimeDatabaseField = DateTimeDatabaseField(name="timestamp")
    team_id: IntegerDatabaseField = IntegerDatabaseField(name="team_id")
    distinct_id: StringDatabaseField = StringDatabaseField(name="distinct_id")
    session_id: StringDatabaseField = StringDatabaseField(name="session_id")
    window_id: StringDatabaseField = StringDatabaseField(name="window_id")
    snapshot_data: StringJSONDatabaseField = StringJSONDatabaseField(name="snapshot_data")
    created_at: DateTimeDatabaseField = DateTimeDatabaseField(name="created_at")
    has_full_snapshot: BooleanDatabaseField = BooleanDatabaseField(name="has_full_snapshot")
    events_summary: StringJSONDatabaseField = StringJSONDatabaseField(name="events_summary", array=True)
    click_count: IntegerDatabaseField = IntegerDatabaseField(name="click_count")
    keypress_count: IntegerDatabaseField = IntegerDatabaseField(name="keypress_count")
    timestamps_summary: DateTimeDatabaseField = DateTimeDatabaseField(name="timestamps_summary", array=True)
    first_event_timestamp: DateTimeDatabaseField = DateTimeDatabaseField(name="first_event_timestamp")
    last_event_timestamp: DateTimeDatabaseField = DateTimeDatabaseField(name="last_event_timestamp")
    urls: StringDatabaseField = StringDatabaseField(name="urls", array=True)

    pdi: JoinedTable = JoinedTable(table=PersonDistinctIdTable(), join_function=join_with_max_person_distinct_id_table)

    def clickhouse_table(self):
        return "session_recording_events"


class Database(BaseModel):
    class Config:
        extra = Extra.forbid

    # Users can query from the tables below
    events: EventsTable = EventsTable()
    persons: PersonsTable = PersonsTable()
    person_distinct_ids: PersonDistinctIdTable = PersonDistinctIdTable()
    session_recording_events: SessionRecordingEvents = SessionRecordingEvents()

    def has_table(self, table_name: str) -> bool:
        return hasattr(self, table_name)

    def get_table(self, table_name: str) -> Table:
        if self.has_table(table_name):
            return getattr(self, table_name)
        raise ValueError(f'Table "{table_name}" not found in database')


database = Database()
