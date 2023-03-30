from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

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
                or isinstance(database_field, LazyJoin)
                or isinstance(database_field, FieldTraverser)
            ):
                pass  # ignore virtual tables for now
            else:
                raise ValueError(f"Unknown field type {type(database_field).__name__} for asterisk")
        return asterisk


class LazyJoin(BaseModel):
    class Config:
        extra = Extra.forbid

    join_function: Callable[[str, str, Dict[str, Any]], Any]
    join_table: Table
    from_field: str


class LazyTable(Table):
    class Config:
        extra = Extra.forbid

    def lazy_select(self, requested_fields: Dict[str, Any]) -> Any:
        raise NotImplementedError("LazyTable.lazy_select not overridden")


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


def select_from_persons_table(requested_fields: Dict[str, Any]):
    from posthog.hogql import ast

    if not requested_fields:
        raise ValueError("No fields requested from persons table.")

    # contains the list of fields we will select from this table
    fields_to_select: List[ast.Expr] = []

    argmax_version: Callable[[ast.Expr], ast.Expr] = lambda field: ast.Call(
        name="argMax", args=[field, ast.Field(chain=["version"])]
    )
    for field, expr in requested_fields.items():
        if field != "id":
            fields_to_select.append(ast.Alias(alias=field, expr=argmax_version(expr)))

    id = ast.Field(chain=["id"])

    return ast.SelectQuery(
        select=fields_to_select + [id],
        select_from=ast.JoinExpr(table=ast.Field(chain=["persons"])),
        group_by=[id],
        having=ast.CompareOperation(
            op=ast.CompareOperationType.Eq,
            left=argmax_version(ast.Field(chain=["is_deleted"])),
            right=ast.Constant(value=0),
        ),
    )


def join_with_persons_table(from_table: str, to_table: str, requested_fields: Dict[str, Any]):
    from posthog.hogql import ast

    if not requested_fields:
        raise ValueError("No fields requested from persons table.")
    join_expr = ast.JoinExpr(table=select_from_persons_table(requested_fields))
    join_expr.join_type = "INNER JOIN"
    join_expr.alias = to_table
    join_expr.constraint = ast.CompareOperation(
        op=ast.CompareOperationType.Eq,
        left=ast.Field(chain=[from_table, "person_id"]),
        right=ast.Field(chain=[to_table, "id"]),
    )
    return join_expr


class LazyPersonsTable(LazyTable):
    id: StringDatabaseField = StringDatabaseField(name="id")
    created_at: DateTimeDatabaseField = DateTimeDatabaseField(name="created_at")
    team_id: IntegerDatabaseField = IntegerDatabaseField(name="team_id")
    properties: StringJSONDatabaseField = StringJSONDatabaseField(name="properties")
    is_identified: BooleanDatabaseField = BooleanDatabaseField(name="is_identified")

    is_deleted: BooleanDatabaseField = BooleanDatabaseField(name="is_deleted")
    version: IntegerDatabaseField = IntegerDatabaseField(name="version")

    def lazy_select(self, requested_fields: Dict[str, Any]):
        return select_from_persons_table(requested_fields)

    def avoid_asterisk_fields(self):
        return ["is_deleted", "version"]

    # def clickhouse_table(self):
    #     raise
    #     # return "person"

    def hogql_table(self):
        return "lazy_persons"


class PersonDistinctIdTable(Table):
    team_id: IntegerDatabaseField = IntegerDatabaseField(name="team_id")
    distinct_id: StringDatabaseField = StringDatabaseField(name="distinct_id")
    person_id: StringDatabaseField = StringDatabaseField(name="person_id")
    is_deleted: BooleanDatabaseField = BooleanDatabaseField(name="is_deleted")
    version: IntegerDatabaseField = IntegerDatabaseField(name="version")

    person: LazyJoin = LazyJoin(
        from_field="person_id", join_table=PersonsTable(), join_function=join_with_persons_table
    )

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
    pdi: LazyJoin = LazyJoin(
        from_field="distinct_id",
        join_table=PersonDistinctIdTable(),
        join_function=join_with_max_person_distinct_id_table,
    )
    # person fields on the event itself
    poe: EventsPersonSubTable = EventsPersonSubTable()

    # These are swapped out if the user has PoE enabled
    person: BaseModel = FieldTraverser(chain=["pdi", "person"])
    person_id: BaseModel = FieldTraverser(chain=["pdi", "person_id"])

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

    pdi: LazyJoin = LazyJoin(
        from_field="distinct_id",
        join_table=PersonDistinctIdTable(),
        join_function=join_with_max_person_distinct_id_table,
    )

    person: FieldTraverser = FieldTraverser(chain=["pdi", "person"])
    person_id: FieldTraverser = FieldTraverser(chain=["pdi", "person_id"])

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

    person: LazyJoin = LazyJoin(
        from_field="person_id", join_table=PersonsTable(), join_function=join_with_persons_table
    )

    def clickhouse_table(self):
        return "cohortpeople"

    def hogql_table(self):
        return "cohort_people"


class StaticCohortPeople(Table):
    person_id: StringDatabaseField = StringDatabaseField(name="person_id")
    cohort_id: IntegerDatabaseField = IntegerDatabaseField(name="cohort_id")
    team_id: IntegerDatabaseField = IntegerDatabaseField(name="team_id")

    person: LazyJoin = LazyJoin(
        from_field="person_id", join_table=PersonsTable(), join_function=join_with_persons_table
    )

    def avoid_asterisk_fields(self):
        return ["_timestamp", "_offset"]

    def clickhouse_table(self):
        return "person_static_cohort"

    def hogql_table(self):
        return "static_cohort_people"


class Groups(Table):
    index: IntegerDatabaseField = IntegerDatabaseField(name="group_type_index")
    key: StringDatabaseField = StringDatabaseField(name="group_key")
    team_id: IntegerDatabaseField = IntegerDatabaseField(name="team_id")
    created_at: DateTimeDatabaseField = DateTimeDatabaseField(name="created_at")
    properties: StringJSONDatabaseField = StringJSONDatabaseField(name="group_properties")

    def clickhouse_table(self):
        return "groups"

    def hogql_table(self):
        return "groups"


class DataBeachTableAppendableRaw(Table):
    class Config:
        extra = Extra.allow

    team_id: IntegerDatabaseField = IntegerDatabaseField(name="team_id")
    id: StringDatabaseField = StringDatabaseField(name="id")
    table_name: StringDatabaseField = StringDatabaseField(name="table_name")
    data: StringJSONDatabaseField = StringJSONDatabaseField(name="data")

    def clickhouse_table(self):
        return "data_beach_appendable"

    def hogql_table(self):
        return "data_beach_appendable_raw"


class Database(BaseModel):
    class Config:
        extra = Extra.allow

    # Users can query from the tables below
    events: EventsTable = EventsTable()
    persons: PersonsTable = PersonsTable()
    lazy_persons: LazyPersonsTable = LazyPersonsTable()
    person_distinct_ids: PersonDistinctIdTable = PersonDistinctIdTable()
    session_recording_events: SessionRecordingEvents = SessionRecordingEvents()
    cohort_people: CohortPeople = CohortPeople()
    static_cohort_people: StaticCohortPeople = StaticCohortPeople()
    groups: Groups = Groups()
    data_beach_appendable_raw: DataBeachTableAppendableRaw = DataBeachTableAppendableRaw()

    def has_table(self, table_name: str) -> bool:
        return hasattr(self, table_name)

    def get_table(self, table_name: str) -> Table:
        if self.has_table(table_name):
            return getattr(self, table_name)
        raise ValueError(f'Table "{table_name}" not found in database')


if TYPE_CHECKING:
    from posthog.models import DataBeachTable


class DataBeachTableAppendable(LazyTable):
    class Config:
        extra = Extra.allow

    data: StringJSONDatabaseField = StringJSONDatabaseField(name="data")

    def __init__(self, table: "DataBeachTable", **kwargs):
        super().__init__(**kwargs)
        self._table = table
        self._table_name = table.name
        self._field_names = [field.name for field in table.fields.all()]

    def lazy_select(self, requested_fields: Dict[str, Any]):
        from posthog.hogql import ast

        if not requested_fields:
            raise ValueError("No fields requested from table.")

        # contains the list of fields we will select from this table
        fields_to_select: List[ast.Expr] = []
        for field, expr in requested_fields.items():
            fields_to_select.append(ast.Alias(alias=field, expr=expr))

        return ast.SelectQuery(
            select=fields_to_select,
            select_from=ast.JoinExpr(table=ast.Field(chain=["data_beach_appendable_raw"])),
            where=ast.CompareOperation(
                op=ast.CompareOperationType.Eq,
                left=ast.Field(chain=["data_beach_appendable_raw", "table_name"]),
                right=ast.Constant(value=self._table_name),
            ),
        )

    def hogql_table(self):
        return self._table_name

    def get_asterisk(self) -> Dict[str, DatabaseField]:
        asterisk: Dict[str, DatabaseField] = {}
        for field in ["id"] + self._field_names:
            asterisk[field] = self.__getattribute__(field)
        return asterisk


def create_hogql_database(team_id: Optional[int]) -> Database:
    from posthog.models import Team, DataBeachTable

    database = Database()
    team = Team.objects.get(pk=team_id)
    if team.person_on_events_querying_enabled:
        database.events.person = FieldTraverser(chain=["poe"])
        database.events.person_id = StringDatabaseField(name="person_id")

    tables = DataBeachTable.objects.filter(team_id=team_id).prefetch_related("fields")

    for table in tables:
        if table.engine == "appendable":
            fields = {}
            for field in table.fields.all():
                fields[field.name] = FieldTraverser(chain=["data", field.name])
            pydantic_table = DataBeachTableAppendable(table=table, **fields)
            for field in table.fields.all():
                pydantic_table.__setattr__(field.name, fields[field.name])
            database.__setattr__(table.name, pydantic_table)

    return database


def serialize_database(database: Database) -> dict:
    tables: Dict[str, List[Dict[str, Any]]] = {}

    for table_key in database.__fields__.keys():
        fields: List[Dict[str, Any]] = []
        table = getattr(database, table_key, None)
        for field_key in table.__fields__.keys() if table else []:
            field = getattr(table, field_key, None)
            if field_key == "team_id":
                pass
            elif isinstance(field, DatabaseField):
                if isinstance(field, IntegerDatabaseField):
                    fields.append({"key": field_key, "type": "integer"})
                elif isinstance(field, StringDatabaseField):
                    fields.append({"key": field_key, "type": "string"})
                elif isinstance(field, DateTimeDatabaseField):
                    fields.append({"key": field_key, "type": "datetime"})
                elif isinstance(field, BooleanDatabaseField):
                    fields.append({"key": field_key, "type": "boolean"})
                elif isinstance(field, StringJSONDatabaseField):
                    fields.append({"key": field_key, "type": "json"})
            elif isinstance(field, LazyJoin):
                fields.append({"key": field_key, "type": "lazy_table", "table": field.join_table.hogql_table()})
            elif isinstance(field, VirtualTable):
                fields.append(
                    {
                        "key": field_key,
                        "type": "virtual_table",
                        "table": field.hogql_table(),
                        "fields": list(field.__fields__.keys()),
                    }
                )
            elif isinstance(field, FieldTraverser):
                fields.append({"key": field_key, "type": "field_traverser", "chain": field.chain})
        tables[table_key] = fields

    return tables
