from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel, Extra


class DatabaseField(BaseModel):
    """Base class for a field in a database table."""

    class Config:
        extra = Extra.forbid

    name: str
    array: Optional[bool]


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

    def hogql_table(self):
        raise NotImplementedError("Table.hogql_table not overridden")

    def avoid_asterisk_fields(self) -> List[str]:
        return []

    def get_asterisk(self) -> Dict[str, DatabaseField]:
        asterisk: Dict[str, DatabaseField] = {}
        fields_to_avoid = self.avoid_asterisk_fields() + ["team_id"]
        for key, field in self.__fields__.items():
            if key in fields_to_avoid:
                continue
            database_field = field.default
            if isinstance(database_field, DatabaseField):
                asterisk[key] = database_field
            elif (
                isinstance(database_field, Table)
                or isinstance(database_field, LazyTable)
                or isinstance(database_field, VirtualTable)
                or isinstance(database_field, FieldTraverser)
            ):
                pass  # ignore virtual tables for now
            else:
                raise ValueError(f"Unknown field type {type(database_field).__name__} for asterisk")
        return asterisk


class LazyTable(BaseModel):
    class Config:
        extra = Extra.forbid

    join_function: Callable[[str, str, Dict[str, Any]], Any]
    table: Table
    from_field: str


class VirtualTable(Table):
    class Config:
        extra = Extra.forbid


class FieldTraverser(BaseModel):
    class Config:
        extra = Extra.forbid

    chain: List[str]


class EventsPersonSubTable(VirtualTable):
    id: StringDatabaseField = StringDatabaseField(name="person_id")
    created_at: DateTimeDatabaseField = DateTimeDatabaseField(name="person_created_at")
    properties: StringJSONDatabaseField = StringJSONDatabaseField(name="person_properties")

    def clickhouse_table(self):
        return "events"

    def hogql_table(self):
        return "events"


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

    def hogql_table(self):
        return "persons"


def join_with_persons_table(from_table: str, to_table: str, requested_fields: Dict[str, Any]):
    from posthog.hogql import ast

    if not requested_fields:
        raise ValueError("No fields requested from persons table. Why are we joining it?")

    # contains the list of fields we will select from this table
    fields_to_select: List[ast.Expr] = []

    argmax_version: Callable[[ast.Expr], ast.Expr] = lambda field: ast.Call(
        name="argMax", args=[field, ast.Field(chain=["version"])]
    )
    for field, expr in requested_fields.items():
        if field != "id":
            fields_to_select.append(ast.Alias(alias=field, expr=argmax_version(expr)))

    id = ast.Field(chain=["id"])

    return ast.JoinExpr(
        join_type="INNER JOIN",
        table=ast.SelectQuery(
            select=fields_to_select + [id],
            select_from=ast.JoinExpr(table=ast.Field(chain=["persons"])),
            group_by=[id],
            having=ast.CompareOperation(
                op=ast.CompareOperationType.Eq,
                left=argmax_version(ast.Field(chain=["is_deleted"])),
                right=ast.Constant(value=0),
            ),
        ),
        alias=to_table,
        constraint=ast.CompareOperation(
            op=ast.CompareOperationType.Eq,
            left=ast.Field(chain=[from_table, "person_id"]),
            right=ast.Field(chain=[to_table, "id"]),
        ),
    )


class PersonDistinctIdTable(Table):
    team_id: IntegerDatabaseField = IntegerDatabaseField(name="team_id")
    distinct_id: StringDatabaseField = StringDatabaseField(name="distinct_id")
    person_id: StringDatabaseField = StringDatabaseField(name="person_id")
    is_deleted: BooleanDatabaseField = BooleanDatabaseField(name="is_deleted")
    version: IntegerDatabaseField = IntegerDatabaseField(name="version")

    person: LazyTable = LazyTable(from_field="person_id", table=PersonsTable(), join_function=join_with_persons_table)

    def avoid_asterisk_fields(self):
        return ["is_deleted", "version"]

    def clickhouse_table(self):
        return "person_distinct_id2"

    def hogql_table(self):
        return "person_distinct_ids"


def join_with_max_person_distinct_id_table(from_table: str, to_table: str, requested_fields: Dict[str, Any]):
    from posthog.hogql import ast

    if not requested_fields:
        requested_fields = {"person_id": ast.Field(chain=["person_id"])}

    # contains the list of fields we will select from this table
    fields_to_select: List[ast.Expr] = []

    argmax_version: Callable[[ast.Expr], ast.Expr] = lambda field: ast.Call(
        name="argMax", args=[field, ast.Field(chain=["version"])]
    )
    for field, expr in requested_fields.items():
        if field != "distinct_id":
            fields_to_select.append(ast.Alias(alias=field, expr=argmax_version(expr)))

    distinct_id = ast.Field(chain=["distinct_id"])

    return ast.JoinExpr(
        join_type="INNER JOIN",
        table=ast.SelectQuery(
            select=fields_to_select + [distinct_id],
            select_from=ast.JoinExpr(table=ast.Field(chain=["person_distinct_ids"])),
            group_by=[distinct_id],
            having=ast.CompareOperation(
                op=ast.CompareOperationType.Eq,
                left=argmax_version(ast.Field(chain=["is_deleted"])),
                right=ast.Constant(value=0),
            ),
        ),
        alias=to_table,
        constraint=ast.CompareOperation(
            op=ast.CompareOperationType.Eq,
            left=ast.Field(chain=[from_table, "distinct_id"]),
            right=ast.Field(chain=[to_table, "distinct_id"]),
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

    # lazy table that adds a join to the persons table
    pdi: LazyTable = LazyTable(
        from_field="distinct_id", table=PersonDistinctIdTable(), join_function=join_with_max_person_distinct_id_table
    )
    # person fields on the event itself
    poe: EventsPersonSubTable = EventsPersonSubTable()

    # TODO: swap these between pdi and person_on_events as needed
    person: FieldTraverser = FieldTraverser(chain=["pdi", "person"])
    person_id: FieldTraverser = FieldTraverser(chain=["pdi", "person_id"])

    def clickhouse_table(self):
        return "events"

    def hogql_table(self):
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

    pdi: LazyTable = LazyTable(
        from_field="distinct_id", table=PersonDistinctIdTable(), join_function=join_with_max_person_distinct_id_table
    )

    def clickhouse_table(self):
        return "session_recording_events"

    def hogql_table(self):
        return "session_recording_events"


class CohortPeople(Table):
    person_id: StringDatabaseField = StringDatabaseField(name="person_id")
    cohort_id: IntegerDatabaseField = IntegerDatabaseField(name="cohort_id")
    team_id: IntegerDatabaseField = IntegerDatabaseField(name="team_id")
    sign: IntegerDatabaseField = IntegerDatabaseField(name="sign")
    version: IntegerDatabaseField = IntegerDatabaseField(name="version")

    # TODO: automatically add "HAVING SUM(sign) > 0" to fields selected from this table?

    person: LazyTable = LazyTable(from_field="person_id", table=PersonsTable(), join_function=join_with_persons_table)

    def clickhouse_table(self):
        return "cohortpeople"


class StaticCohortPeople(Table):
    person_id: StringDatabaseField = StringDatabaseField(name="person_id")
    cohort_id: IntegerDatabaseField = IntegerDatabaseField(name="cohort_id")
    team_id: IntegerDatabaseField = IntegerDatabaseField(name="team_id")

    person: LazyTable = LazyTable(from_field="person_id", table=PersonsTable(), join_function=join_with_persons_table)

    def avoid_asterisk_fields(self):
        return ["_timestamp", "_offset"]

    def clickhouse_table(self):
        return "person_static_cohort"


class Database(BaseModel):
    class Config:
        extra = Extra.forbid

    # Users can query from the tables below
    events: EventsTable = EventsTable()
    persons: PersonsTable = PersonsTable()
    person_distinct_ids: PersonDistinctIdTable = PersonDistinctIdTable()
    session_recording_events: SessionRecordingEvents = SessionRecordingEvents()
    cohort_people: CohortPeople = CohortPeople()
    static_cohort_people: StaticCohortPeople = StaticCohortPeople()

    def has_table(self, table_name: str) -> bool:
        return hasattr(self, table_name)

    def get_table(self, table_name: str) -> Table:
        if self.has_table(table_name):
            return getattr(self, table_name)
        raise ValueError(f'Table "{table_name}" not found in database')


database = Database()
