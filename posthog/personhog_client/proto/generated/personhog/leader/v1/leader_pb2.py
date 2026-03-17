"""Generated protocol buffer code."""

from google.protobuf import (
    descriptor as _descriptor,
    descriptor_pool as _descriptor_pool,
    runtime_version as _runtime_version,
    symbol_database as _symbol_database,
)
from google.protobuf.internal import builder as _builder

_runtime_version.ValidateProtobufRuntimeVersion(
    _runtime_version.Domain.PUBLIC, 5, 29, 0, "", "personhog/leader/v1/leader.proto"
)
_sym_db = _symbol_database.Default()
from ....personhog.types.v1 import person_pb2 as personhog_dot_types_dot_v1_dot_person__pb2

DESCRIPTOR = _descriptor_pool.Default().AddSerializedFile(
    b'\n personhog/leader/v1/leader.proto\x12\x13personhog.leader.v1\x1a\x1fpersonhog/types/v1/person.proto"\xb9\x01\n\x1dUpdatePersonPropertiesRequest\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12\x11\n\tperson_id\x18\x02 \x01(\x03\x12\x12\n\nevent_name\x18\x03 \x01(\t\x12\x16\n\x0eset_properties\x18\x04 \x01(\x0c\x12\x1b\n\x13set_once_properties\x18\x05 \x01(\x0c\x12\x18\n\x10unset_properties\x18\x06 \x03(\t\x12\x11\n\tpartition\x18\x07 \x01(\r"O\n\x16LeaderGetPersonRequest\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12\x11\n\tperson_id\x18\x02 \x01(\x03\x12\x11\n\tpartition\x18\x03 \x01(\r"m\n\x1eUpdatePersonPropertiesResponse\x12/\n\x06person\x18\x01 \x01(\x0b2\x1a.personhog.types.v1.PersonH\x00\x88\x01\x01\x12\x0f\n\x07updated\x18\x02 \x01(\x08B\t\n\x07_person2\xf6\x01\n\x0fPersonHogLeader\x12\x81\x01\n\x16UpdatePersonProperties\x122.personhog.leader.v1.UpdatePersonPropertiesRequest\x1a3.personhog.leader.v1.UpdatePersonPropertiesResponse\x12_\n\tGetPerson\x12+.personhog.leader.v1.LeaderGetPersonRequest\x1a%.personhog.types.v1.GetPersonResponseb\x06proto3'
)
_globals = globals()
_builder.BuildMessageAndEnumDescriptors(DESCRIPTOR, _globals)
_builder.BuildTopDescriptorsAndMessages(DESCRIPTOR, "personhog.leader.v1.leader_pb2", _globals)
if not _descriptor._USE_C_DESCRIPTORS:
    DESCRIPTOR._loaded_options = None
    _globals["_UPDATEPERSONPROPERTIESREQUEST"]._serialized_start = 91
    _globals["_UPDATEPERSONPROPERTIESREQUEST"]._serialized_end = 276
    _globals["_LEADERGETPERSONREQUEST"]._serialized_start = 278
    _globals["_LEADERGETPERSONREQUEST"]._serialized_end = 357
    _globals["_UPDATEPERSONPROPERTIESRESPONSE"]._serialized_start = 359
    _globals["_UPDATEPERSONPROPERTIESRESPONSE"]._serialized_end = 468
    _globals["_PERSONHOGLEADER"]._serialized_start = 471
    _globals["_PERSONHOGLEADER"]._serialized_end = 717
