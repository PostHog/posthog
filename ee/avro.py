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


def dict_to_arrays(old_dict: dict):
    key_list = []
    value_list = []
    for k, v in old_dict.items():
        key_list.append(k)
        value_list.append(str(v))
    return key_list, value_list


def get_schema(schema_name):
    schema_location = os.path.join(SCHEMA_LOCATION, schema_name + ".avsc")
    schema = avro.schema.parse(open(schema_location, "rb").read())
    return schema


def encode(schema_name: str, data: any) -> bytes:
    schema = get_schema(schema_name)
    writer = avro.io.DatumWriter(schema)
    bytes_writer = io.BytesIO()
    encoder = avro.io.BinaryEncoder(bytes_writer)
    writer.write(data, encoder)
    raw_bytes = bytes_writer.getvalue()
    return raw_bytes


def decode(schema_name: str, data: bytes) -> any:
    schema = get_schema(schema_name)
    message = data.value()
    bytes_reader = io.BytesIO(message)
    decoder = avro.io.BinaryDecoder(bytes_reader)
    reader = avro.io.DatumReader(schema)
    return reader.read(decoder)
