import io
import os

import avro
from avro.datafile import DataFileReader, DataFileWriter
from avro.io import DatumReader, DatumWriter

SCHEMA_LOCATION = os.path.join("ee", "idl")

# Schema types
PERSON_SCHEMA = "person"
PERSON_DISTINCT_SCHEMA = "person_distinct"
ELEMENT_SCHEMA = "element"
ELEMENT_GROUP_SCHEMA = "element_group"
EVENT_SCHEMA = "event"


def string_map_values(old_dict: dict):
    new_dict = {}
    for k, v in old_dict.items():
        new_dict[k] = str(v)
    return new_dict


def get_schema(schema_name):
    schema_location = os.path.join(SCHEMA_LOCATION, schema_name + ".avsc")
    schema = avro.schema.parse(open(schema_location, "rb").read())
    return schema


def encode(schema_name: str, data: any) -> bytes:
    schema = get_schema(schema_name)
    buf = io.BytesIO()
    writer = DataFileWriter(buf, DatumWriter(), schema)
    writer.append(data)
    writer.flush()
    buf.seek(0)
    return buf.read()


def decode(data: bytes) -> any:
    data_buf = io.BytesIO(data)
    reader = DataFileReader(data_buf, DatumReader())
    return reader
