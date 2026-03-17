"""Generated protocol buffer code."""

from google.protobuf import (
    descriptor as _descriptor,
    descriptor_pool as _descriptor_pool,
    runtime_version as _runtime_version,
    symbol_database as _symbol_database,
)
from google.protobuf.internal import builder as _builder

_runtime_version.ValidateProtobufRuntimeVersion(
    _runtime_version.Domain.PUBLIC, 5, 29, 0, "", "personhog/types/v1/person.proto"
)
_sym_db = _symbol_database.Default()
from ....personhog.types.v1 import common_pb2 as personhog_dot_types_dot_v1_dot_common__pb2

DESCRIPTOR = _descriptor_pool.Default().AddSerializedFile(
    b'\n\x1fpersonhog/types/v1/person.proto\x12\x12personhog.types.v1\x1a\x1fpersonhog/types/v1/common.proto"\x9e\x02\n\x06Person\x12\n\n\x02id\x18\x01 \x01(\x03\x12\x0c\n\x04uuid\x18\x02 \x01(\t\x12\x0f\n\x07team_id\x18\x03 \x01(\x03\x12\x12\n\nproperties\x18\x04 \x01(\x0c\x12"\n\x1aproperties_last_updated_at\x18\x05 \x01(\x0c\x12!\n\x19properties_last_operation\x18\x06 \x01(\x0c\x12\x12\n\ncreated_at\x18\x07 \x01(\x03\x12\x0f\n\x07version\x18\x08 \x01(\x03\x12\x15\n\ris_identified\x18\t \x01(\x08\x12\x17\n\nis_user_id\x18\n \x01(\x08H\x00\x88\x01\x01\x12\x19\n\x0clast_seen_at\x18\x0b \x01(\x03H\x01\x88\x01\x01B\r\n\x0b_is_user_idB\x0f\n\r_last_seen_at"N\n\x15DistinctIdWithVersion\x12\x13\n\x0bdistinct_id\x18\x01 \x01(\t\x12\x14\n\x07version\x18\x02 \x01(\x03H\x00\x88\x01\x01B\n\n\x08_version"h\n\x15PersonWithDistinctIds\x12\x13\n\x0bdistinct_id\x18\x01 \x01(\t\x12/\n\x06person\x18\x02 \x01(\x0b2\x1a.personhog.types.v1.PersonH\x00\x88\x01\x01B\t\n\x07_person"g\n\x11PersonDistinctIds\x12\x11\n\tperson_id\x18\x01 \x01(\x03\x12?\n\x0cdistinct_ids\x18\x02 \x03(\x0b2).personhog.types.v1.DistinctIdWithVersion"\x87\x01\n\x18PersonWithTeamDistinctId\x12/\n\x03key\x18\x01 \x01(\x0b2".personhog.types.v1.TeamDistinctId\x12/\n\x06person\x18\x02 \x01(\x0b2\x1a.personhog.types.v1.PersonH\x00\x88\x01\x01B\t\n\x07_person"m\n\x10GetPersonRequest\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12\x11\n\tperson_id\x18\x02 \x01(\x03\x125\n\x0cread_options\x18\x03 \x01(\x0b2\x1f.personhog.types.v1.ReadOptions"O\n\x11GetPersonResponse\x12/\n\x06person\x18\x01 \x01(\x0b2\x1a.personhog.types.v1.PersonH\x00\x88\x01\x01B\t\n\x07_person"o\n\x11GetPersonsRequest\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12\x12\n\nperson_ids\x18\x02 \x03(\x03\x125\n\x0cread_options\x18\x03 \x01(\x0b2\x1f.personhog.types.v1.ReadOptions"S\n\x0fPersonsResponse\x12+\n\x07persons\x18\x01 \x03(\x0b2\x1a.personhog.types.v1.Person\x12\x13\n\x0bmissing_ids\x18\x02 \x03(\x03"n\n\x16GetPersonByUuidRequest\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12\x0c\n\x04uuid\x18\x02 \x01(\t\x125\n\x0cread_options\x18\x03 \x01(\x0b2\x1f.personhog.types.v1.ReadOptions"q\n\x18GetPersonsByUuidsRequest\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12\r\n\x05uuids\x18\x02 \x03(\t\x125\n\x0cread_options\x18\x03 \x01(\x0b2\x1f.personhog.types.v1.ReadOptions"{\n\x1cGetPersonByDistinctIdRequest\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12\x13\n\x0bdistinct_id\x18\x02 \x01(\t\x125\n\x0cread_options\x18\x03 \x01(\x0b2\x1f.personhog.types.v1.ReadOptions"\x84\x01\n$GetPersonsByDistinctIdsInTeamRequest\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12\x14\n\x0cdistinct_ids\x18\x02 \x03(\t\x125\n\x0cread_options\x18\x03 \x01(\x0b2\x1f.personhog.types.v1.ReadOptions"`\n"PersonsByDistinctIdsInTeamResponse\x12:\n\x07results\x18\x01 \x03(\x0b2).personhog.types.v1.PersonWithDistinctIds"\x96\x01\n\x1eGetPersonsByDistinctIdsRequest\x12=\n\x11team_distinct_ids\x18\x01 \x03(\x0b2".personhog.types.v1.TeamDistinctId\x125\n\x0cread_options\x18\x02 \x01(\x0b2\x1f.personhog.types.v1.ReadOptions"]\n\x1cPersonsByDistinctIdsResponse\x12=\n\x07results\x18\x01 \x03(\x0b2,.personhog.types.v1.PersonWithTeamDistinctId"{\n\x1eGetDistinctIdsForPersonRequest\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12\x11\n\tperson_id\x18\x02 \x01(\x03\x125\n\x0cread_options\x18\x03 \x01(\x0b2\x1f.personhog.types.v1.ReadOptions"b\n\x1fGetDistinctIdsForPersonResponse\x12?\n\x0cdistinct_ids\x18\x01 \x03(\x0b2).personhog.types.v1.DistinctIdWithVersion"}\n\x1fGetDistinctIdsForPersonsRequest\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12\x12\n\nperson_ids\x18\x02 \x03(\x03\x125\n\x0cread_options\x18\x03 \x01(\x0b2\x1f.personhog.types.v1.ReadOptions"f\n GetDistinctIdsForPersonsResponse\x12B\n\x13person_distinct_ids\x18\x01 \x03(\x0b2%.personhog.types.v1.PersonDistinctIdsb\x06proto3'
)
_globals = globals()
_builder.BuildMessageAndEnumDescriptors(DESCRIPTOR, _globals)
_builder.BuildTopDescriptorsAndMessages(DESCRIPTOR, "personhog.types.v1.person_pb2", _globals)
if not _descriptor._USE_C_DESCRIPTORS:
    DESCRIPTOR._loaded_options = None
    _globals["_PERSON"]._serialized_start = 89
    _globals["_PERSON"]._serialized_end = 375
    _globals["_DISTINCTIDWITHVERSION"]._serialized_start = 377
    _globals["_DISTINCTIDWITHVERSION"]._serialized_end = 455
    _globals["_PERSONWITHDISTINCTIDS"]._serialized_start = 457
    _globals["_PERSONWITHDISTINCTIDS"]._serialized_end = 561
    _globals["_PERSONDISTINCTIDS"]._serialized_start = 563
    _globals["_PERSONDISTINCTIDS"]._serialized_end = 666
    _globals["_PERSONWITHTEAMDISTINCTID"]._serialized_start = 669
    _globals["_PERSONWITHTEAMDISTINCTID"]._serialized_end = 804
    _globals["_GETPERSONREQUEST"]._serialized_start = 806
    _globals["_GETPERSONREQUEST"]._serialized_end = 915
    _globals["_GETPERSONRESPONSE"]._serialized_start = 917
    _globals["_GETPERSONRESPONSE"]._serialized_end = 996
    _globals["_GETPERSONSREQUEST"]._serialized_start = 998
    _globals["_GETPERSONSREQUEST"]._serialized_end = 1109
    _globals["_PERSONSRESPONSE"]._serialized_start = 1111
    _globals["_PERSONSRESPONSE"]._serialized_end = 1194
    _globals["_GETPERSONBYUUIDREQUEST"]._serialized_start = 1196
    _globals["_GETPERSONBYUUIDREQUEST"]._serialized_end = 1306
    _globals["_GETPERSONSBYUUIDSREQUEST"]._serialized_start = 1308
    _globals["_GETPERSONSBYUUIDSREQUEST"]._serialized_end = 1421
    _globals["_GETPERSONBYDISTINCTIDREQUEST"]._serialized_start = 1423
    _globals["_GETPERSONBYDISTINCTIDREQUEST"]._serialized_end = 1546
    _globals["_GETPERSONSBYDISTINCTIDSINTEAMREQUEST"]._serialized_start = 1549
    _globals["_GETPERSONSBYDISTINCTIDSINTEAMREQUEST"]._serialized_end = 1681
    _globals["_PERSONSBYDISTINCTIDSINTEAMRESPONSE"]._serialized_start = 1683
    _globals["_PERSONSBYDISTINCTIDSINTEAMRESPONSE"]._serialized_end = 1779
    _globals["_GETPERSONSBYDISTINCTIDSREQUEST"]._serialized_start = 1782
    _globals["_GETPERSONSBYDISTINCTIDSREQUEST"]._serialized_end = 1932
    _globals["_PERSONSBYDISTINCTIDSRESPONSE"]._serialized_start = 1934
    _globals["_PERSONSBYDISTINCTIDSRESPONSE"]._serialized_end = 2027
    _globals["_GETDISTINCTIDSFORPERSONREQUEST"]._serialized_start = 2029
    _globals["_GETDISTINCTIDSFORPERSONREQUEST"]._serialized_end = 2152
    _globals["_GETDISTINCTIDSFORPERSONRESPONSE"]._serialized_start = 2154
    _globals["_GETDISTINCTIDSFORPERSONRESPONSE"]._serialized_end = 2252
    _globals["_GETDISTINCTIDSFORPERSONSREQUEST"]._serialized_start = 2254
    _globals["_GETDISTINCTIDSFORPERSONSREQUEST"]._serialized_end = 2379
    _globals["_GETDISTINCTIDSFORPERSONSRESPONSE"]._serialized_start = 2381
    _globals["_GETDISTINCTIDSFORPERSONSRESPONSE"]._serialized_end = 2483
