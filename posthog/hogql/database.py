from pydantic import BaseModel, Extra


class Field(BaseModel):
    class Config:
        extra = Extra.forbid


class IntegerValue(Field):
    pass


class StringValue(Field):
    pass


class StringJSONValue(Field):
    pass


class DateTimeValue(Field):
    pass


class BooleanValue(Field):
    pass


class ArrayValue(Field):
    field: Field


class Table(BaseModel):
    class Config:
        extra = Extra.forbid

    def clickhouse_table(self):
        raise NotImplementedError()


class PersonsTable(Table):
    id: StringValue = StringValue()
    created_at: DateTimeValue = DateTimeValue()
    team_id: IntegerValue = IntegerValue()
    properties: StringJSONValue = StringJSONValue()
    is_identified: BooleanValue = BooleanValue()
    is_deleted: BooleanValue = BooleanValue()
    version: IntegerValue = IntegerValue()

    def clickhouse_table(self):
        return "person"


class PersonDistinctIdTable(Table):
    team_id: IntegerValue = IntegerValue()
    distinct_id: StringValue = StringValue()
    person_id: StringValue = StringValue()
    is_deleted: BooleanValue = BooleanValue()
    version: IntegerValue = IntegerValue()

    def clickhouse_table(self):
        return "person_distinct_id2"


class PersonFieldsOnEvents(Table):
    id: StringValue = StringValue()
    created_at: DateTimeValue = DateTimeValue()
    properties: StringJSONValue = StringJSONValue()


class EventsTable(Table):
    uuid: StringValue = StringValue()
    event: StringValue = StringValue()
    timestamp: DateTimeValue = DateTimeValue()
    properties: StringJSONValue = StringJSONValue()
    elements_chain: StringValue = StringValue()
    created_at: DateTimeValue = DateTimeValue()
    distinct_id: StringValue = StringValue()
    team_id: IntegerValue = IntegerValue()
    person: PersonFieldsOnEvents = PersonFieldsOnEvents()

    def clickhouse_table(self):
        return "events"


class SessionRecordingEvents(Table):
    uuid: StringValue = StringValue()
    timestamp: DateTimeValue = DateTimeValue()
    team_id: IntegerValue = IntegerValue()
    distinct_id: StringValue = StringValue()
    session_id: StringValue = StringValue()
    window_id: StringValue = StringValue()
    snapshot_data: StringValue = StringValue()
    created_at: DateTimeValue = DateTimeValue()
    has_full_snapshot: BooleanValue = BooleanValue()
    events_summary: ArrayValue = ArrayValue(field=BooleanValue())
    click_count: IntegerValue = IntegerValue()
    keypress_count: IntegerValue = IntegerValue()
    timestamps_summary: ArrayValue = ArrayValue(field=DateTimeValue())
    first_event_timestamp: DateTimeValue = DateTimeValue()
    last_event_timestamp: DateTimeValue = DateTimeValue()
    urls: ArrayValue = ArrayValue(field=StringValue())

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


database = Database()
