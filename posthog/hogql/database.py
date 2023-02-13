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


# class NumbersTable(Table):
#     args: [IntegerValue, IntegerValue]


class Database(BaseModel):
    class Config:
        extra = Extra.forbid

    # All fields below will be tables users can query from
    events: EventsTable = EventsTable()
    persons: PersonsTable = PersonsTable()
    person_distinct_id: PersonDistinctIdTable = PersonDistinctIdTable()
    # numbers: NumbersTable = NumbersTable()


database = Database()
