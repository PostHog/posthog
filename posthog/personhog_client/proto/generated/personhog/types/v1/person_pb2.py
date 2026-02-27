"""Generated protocol buffer code."""

from google.protobuf import (
    descriptor as _descriptor,
    descriptor_pool as _descriptor_pool,
    runtime_version as _runtime_version,
    symbol_database as _symbol_database,
)
from google.protobuf.internal import builder as _builder

_runtime_version.ValidateProtobufRuntimeVersion(
    _runtime_version.Domain.PUBLIC, 5, 29, 3, "", "personhog/types/v1/person.proto"
)
_sym_db = _symbol_database.Default()
DESCRIPTOR = _descriptor_pool.Default().AddSerializedFile(
    b'\n\x1fpersonhog/types/v1/person.proto\x12\x12personhog.types.v1\x1a\x1fpersonhog/types/v1/common.proto"\xda\x02\n\x06Person\x12\x0e\n\x02id\x18\x01 \x01(\x03R\x02id\x12\x12\n\x04uuid\x18\x02 \x01(\tR\x04uuid\x12\x17\n\x07team_id\x18\x03 \x01(\x03R\x06teamId\x12\x1e\n\nproperties\x18\x04 \x01(\x0cR\nproperties\x12;\n\x1aproperties_last_updated_at\x18\x05 \x01(\x0cR\x17propertiesLastUpdatedAt\x12:\n\x19properties_last_operation\x18\x06 \x01(\x0cR\x17propertiesLastOperation\x12\x1d\n\ncreated_at\x18\x07 \x01(\x03R\tcreatedAt\x12\x18\n\x07version\x18\x08 \x01(\x03R\x07version\x12#\n\ris_identified\x18\t \x01(\x08R\x0cisIdentified\x12\x1c\n\nis_user_id\x18\n \x01(\x08R\x08isUserId"c\n\x15DistinctIdWithVersion\x12\x1f\n\x0bdistinct_id\x18\x01 \x01(\tR\ndistinctId\x12\x1d\n\x07version\x18\x02 \x01(\x03H\x00R\x07version\x88\x01\x01B\n\n\x08_version"|\n\x15PersonWithDistinctIds\x12\x1f\n\x0bdistinct_id\x18\x01 \x01(\tR\ndistinctId\x127\n\x06person\x18\x02 \x01(\x0b2\x1a.personhog.types.v1.PersonH\x00R\x06person\x88\x01\x01B\t\n\x07_person"~\n\x11PersonDistinctIds\x12\x1b\n\tperson_id\x18\x01 \x01(\x03R\x08personId\x12L\n\x0cdistinct_ids\x18\x02 \x03(\x0b2).personhog.types.v1.DistinctIdWithVersionR\x0bdistinctIds"\x94\x01\n\x18PersonWithTeamDistinctId\x124\n\x03key\x18\x01 \x01(\x0b2".personhog.types.v1.TeamDistinctIdR\x03key\x127\n\x06person\x18\x02 \x01(\x0b2\x1a.personhog.types.v1.PersonH\x00R\x06person\x88\x01\x01B\t\n\x07_person"\x8c\x01\n\x10GetPersonRequest\x12\x17\n\x07team_id\x18\x01 \x01(\x03R\x06teamId\x12\x1b\n\tperson_id\x18\x02 \x01(\x03R\x08personId\x12B\n\x0cread_options\x18\x03 \x01(\x0b2\x1f.personhog.types.v1.ReadOptionsR\x0breadOptions"W\n\x11GetPersonResponse\x127\n\x06person\x18\x01 \x01(\x0b2\x1a.personhog.types.v1.PersonH\x00R\x06person\x88\x01\x01B\t\n\x07_person"\x8f\x01\n\x11GetPersonsRequest\x12\x17\n\x07team_id\x18\x01 \x01(\x03R\x06teamId\x12\x1d\n\nperson_ids\x18\x02 \x03(\x03R\tpersonIds\x12B\n\x0cread_options\x18\x03 \x01(\x0b2\x1f.personhog.types.v1.ReadOptionsR\x0breadOptions"h\n\x0fPersonsResponse\x124\n\x07persons\x18\x01 \x03(\x0b2\x1a.personhog.types.v1.PersonR\x07persons\x12\x1f\n\x0bmissing_ids\x18\x02 \x03(\x03R\nmissingIds"\x89\x01\n\x16GetPersonByUuidRequest\x12\x17\n\x07team_id\x18\x01 \x01(\x03R\x06teamId\x12\x12\n\x04uuid\x18\x02 \x01(\tR\x04uuid\x12B\n\x0cread_options\x18\x03 \x01(\x0b2\x1f.personhog.types.v1.ReadOptionsR\x0breadOptions"\x8d\x01\n\x18GetPersonsByUuidsRequest\x12\x17\n\x07team_id\x18\x01 \x01(\x03R\x06teamId\x12\x14\n\x05uuids\x18\x02 \x03(\tR\x05uuids\x12B\n\x0cread_options\x18\x03 \x01(\x0b2\x1f.personhog.types.v1.ReadOptionsR\x0breadOptions"\x9c\x01\n\x1cGetPersonByDistinctIdRequest\x12\x17\n\x07team_id\x18\x01 \x01(\x03R\x06teamId\x12\x1f\n\x0bdistinct_id\x18\x02 \x01(\tR\ndistinctId\x12B\n\x0cread_options\x18\x03 \x01(\x0b2\x1f.personhog.types.v1.ReadOptionsR\x0breadOptions"\xa6\x01\n$GetPersonsByDistinctIdsInTeamRequest\x12\x17\n\x07team_id\x18\x01 \x01(\x03R\x06teamId\x12!\n\x0cdistinct_ids\x18\x02 \x03(\tR\x0bdistinctIds\x12B\n\x0cread_options\x18\x03 \x01(\x0b2\x1f.personhog.types.v1.ReadOptionsR\x0breadOptions"i\n"PersonsByDistinctIdsInTeamResponse\x12C\n\x07results\x18\x01 \x03(\x0b2).personhog.types.v1.PersonWithDistinctIdsR\x07results"\xb4\x01\n\x1eGetPersonsByDistinctIdsRequest\x12N\n\x11team_distinct_ids\x18\x01 \x03(\x0b2".personhog.types.v1.TeamDistinctIdR\x0fteamDistinctIds\x12B\n\x0cread_options\x18\x02 \x01(\x0b2\x1f.personhog.types.v1.ReadOptionsR\x0breadOptions"f\n\x1cPersonsByDistinctIdsResponse\x12F\n\x07results\x18\x01 \x03(\x0b2,.personhog.types.v1.PersonWithTeamDistinctIdR\x07results"\x9a\x01\n\x1eGetDistinctIdsForPersonRequest\x12\x17\n\x07team_id\x18\x01 \x01(\x03R\x06teamId\x12\x1b\n\tperson_id\x18\x02 \x01(\x03R\x08personId\x12B\n\x0cread_options\x18\x03 \x01(\x0b2\x1f.personhog.types.v1.ReadOptionsR\x0breadOptions"o\n\x1fGetDistinctIdsForPersonResponse\x12L\n\x0cdistinct_ids\x18\x01 \x03(\x0b2).personhog.types.v1.DistinctIdWithVersionR\x0bdistinctIds"\x9d\x01\n\x1fGetDistinctIdsForPersonsRequest\x12\x17\n\x07team_id\x18\x01 \x01(\x03R\x06teamId\x12\x1d\n\nperson_ids\x18\x02 \x03(\x03R\tpersonIds\x12B\n\x0cread_options\x18\x03 \x01(\x0b2\x1f.personhog.types.v1.ReadOptionsR\x0breadOptions"y\n GetDistinctIdsForPersonsResponse\x12U\n\x13person_distinct_ids\x18\x01 \x03(\x0b2%.personhog.types.v1.PersonDistinctIdsR\x11personDistinctIdsb\x06proto3'
)
_globals = globals()
_builder.BuildMessageAndEnumDescriptors(DESCRIPTOR, _globals)
_builder.BuildTopDescriptorsAndMessages(DESCRIPTOR, "personhog.types.v1.person_pb2", _globals)
if not _descriptor._USE_C_DESCRIPTORS:
    DESCRIPTOR._loaded_options = None
    _globals["_PERSON"]._serialized_start = 89
    _globals["_PERSON"]._serialized_end = 435
    _globals["_DISTINCTIDWITHVERSION"]._serialized_start = 437
    _globals["_DISTINCTIDWITHVERSION"]._serialized_end = 536
    _globals["_PERSONWITHDISTINCTIDS"]._serialized_start = 538
    _globals["_PERSONWITHDISTINCTIDS"]._serialized_end = 662
    _globals["_PERSONDISTINCTIDS"]._serialized_start = 664
    _globals["_PERSONDISTINCTIDS"]._serialized_end = 790
    _globals["_PERSONWITHTEAMDISTINCTID"]._serialized_start = 793
    _globals["_PERSONWITHTEAMDISTINCTID"]._serialized_end = 941
    _globals["_GETPERSONREQUEST"]._serialized_start = 944
    _globals["_GETPERSONREQUEST"]._serialized_end = 1084
    _globals["_GETPERSONRESPONSE"]._serialized_start = 1086
    _globals["_GETPERSONRESPONSE"]._serialized_end = 1173
    _globals["_GETPERSONSREQUEST"]._serialized_start = 1176
    _globals["_GETPERSONSREQUEST"]._serialized_end = 1319
    _globals["_PERSONSRESPONSE"]._serialized_start = 1321
    _globals["_PERSONSRESPONSE"]._serialized_end = 1425
    _globals["_GETPERSONBYUUIDREQUEST"]._serialized_start = 1428
    _globals["_GETPERSONBYUUIDREQUEST"]._serialized_end = 1565
    _globals["_GETPERSONSBYUUIDSREQUEST"]._serialized_start = 1568
    _globals["_GETPERSONSBYUUIDSREQUEST"]._serialized_end = 1709
    _globals["_GETPERSONBYDISTINCTIDREQUEST"]._serialized_start = 1712
    _globals["_GETPERSONBYDISTINCTIDREQUEST"]._serialized_end = 1868
    _globals["_GETPERSONSBYDISTINCTIDSINTEAMREQUEST"]._serialized_start = 1871
    _globals["_GETPERSONSBYDISTINCTIDSINTEAMREQUEST"]._serialized_end = 2037
    _globals["_PERSONSBYDISTINCTIDSINTEAMRESPONSE"]._serialized_start = 2039
    _globals["_PERSONSBYDISTINCTIDSINTEAMRESPONSE"]._serialized_end = 2144
    _globals["_GETPERSONSBYDISTINCTIDSREQUEST"]._serialized_start = 2147
    _globals["_GETPERSONSBYDISTINCTIDSREQUEST"]._serialized_end = 2327
    _globals["_PERSONSBYDISTINCTIDSRESPONSE"]._serialized_start = 2329
    _globals["_PERSONSBYDISTINCTIDSRESPONSE"]._serialized_end = 2431
    _globals["_GETDISTINCTIDSFORPERSONREQUEST"]._serialized_start = 2434
    _globals["_GETDISTINCTIDSFORPERSONREQUEST"]._serialized_end = 2588
    _globals["_GETDISTINCTIDSFORPERSONRESPONSE"]._serialized_start = 2590
    _globals["_GETDISTINCTIDSFORPERSONRESPONSE"]._serialized_end = 2701
    _globals["_GETDISTINCTIDSFORPERSONSREQUEST"]._serialized_start = 2704
    _globals["_GETDISTINCTIDSFORPERSONSREQUEST"]._serialized_end = 2861
    _globals["_GETDISTINCTIDSFORPERSONSRESPONSE"]._serialized_start = 2863
    _globals["_GETDISTINCTIDSFORPERSONSRESPONSE"]._serialized_end = 2984
