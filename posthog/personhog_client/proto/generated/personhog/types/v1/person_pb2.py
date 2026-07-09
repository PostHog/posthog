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
    b'\n\x1fpersonhog/types/v1/person.proto\x12\x12personhog.types.v1\x1a\x1fpersonhog/types/v1/common.proto"\xe7\x02\n\x06Person\x12\n\n\x02id\x18\x01 \x01(\x03\x12\x0c\n\x04uuid\x18\x02 \x01(\t\x12\x0f\n\x07team_id\x18\x03 \x01(\x03\x12\x12\n\nproperties\x18\x04 \x01(\x0c\x12"\n\x1aproperties_last_updated_at\x18\x05 \x01(\x0c\x12!\n\x19properties_last_operation\x18\x06 \x01(\x0c\x12\x12\n\ncreated_at\x18\x07 \x01(\x03\x12\x0f\n\x07version\x18\x08 \x01(\x03\x12\x15\n\ris_identified\x18\t \x01(\x08\x12\x17\n\nis_user_id\x18\n \x01(\x08H\x00\x88\x01\x01\x12\x19\n\x0clast_seen_at\x18\x0b \x01(\x03H\x01\x88\x01\x01\x12G\n\x14initial_distinct_ids\x18\x0c \x03(\x0b2).personhog.types.v1.DistinctIdWithVersionB\r\n\x0b_is_user_idB\x0f\n\r_last_seen_at"N\n\x15DistinctIdWithVersion\x12\x13\n\x0bdistinct_id\x18\x01 \x01(\t\x12\x14\n\x07version\x18\x02 \x01(\x03H\x00\x88\x01\x01B\n\n\x08_version"h\n\x15PersonWithDistinctIds\x12\x13\n\x0bdistinct_id\x18\x01 \x01(\t\x12/\n\x06person\x18\x02 \x01(\x0b2\x1a.personhog.types.v1.PersonH\x00\x88\x01\x01B\t\n\x07_person"g\n\x11PersonDistinctIds\x12\x11\n\tperson_id\x18\x01 \x01(\x03\x12?\n\x0cdistinct_ids\x18\x02 \x03(\x0b2).personhog.types.v1.DistinctIdWithVersion"\x87\x01\n\x18PersonWithTeamDistinctId\x12/\n\x03key\x18\x01 \x01(\x0b2".personhog.types.v1.TeamDistinctId\x12/\n\x06person\x18\x02 \x01(\x0b2\x1a.personhog.types.v1.PersonH\x00\x88\x01\x01B\t\n\x07_person"m\n\x10GetPersonRequest\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12\x11\n\tperson_id\x18\x02 \x01(\x03\x125\n\x0cread_options\x18\x03 \x01(\x0b2\x1f.personhog.types.v1.ReadOptions"O\n\x11GetPersonResponse\x12/\n\x06person\x18\x01 \x01(\x0b2\x1a.personhog.types.v1.PersonH\x00\x88\x01\x01B\t\n\x07_person"o\n\x11GetPersonsRequest\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12\x12\n\nperson_ids\x18\x02 \x03(\x03\x125\n\x0cread_options\x18\x03 \x01(\x0b2\x1f.personhog.types.v1.ReadOptions"S\n\x0fPersonsResponse\x12+\n\x07persons\x18\x01 \x03(\x0b2\x1a.personhog.types.v1.Person\x12\x13\n\x0bmissing_ids\x18\x02 \x03(\x03"n\n\x16GetPersonByUuidRequest\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12\x0c\n\x04uuid\x18\x02 \x01(\t\x125\n\x0cread_options\x18\x03 \x01(\x0b2\x1f.personhog.types.v1.ReadOptions"q\n\x18GetPersonsByUuidsRequest\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12\r\n\x05uuids\x18\x02 \x03(\t\x125\n\x0cread_options\x18\x03 \x01(\x0b2\x1f.personhog.types.v1.ReadOptions"{\n\x1cGetPersonByDistinctIdRequest\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12\x13\n\x0bdistinct_id\x18\x02 \x01(\t\x125\n\x0cread_options\x18\x03 \x01(\x0b2\x1f.personhog.types.v1.ReadOptions"\x84\x01\n$GetPersonsByDistinctIdsInTeamRequest\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12\x14\n\x0cdistinct_ids\x18\x02 \x03(\t\x125\n\x0cread_options\x18\x03 \x01(\x0b2\x1f.personhog.types.v1.ReadOptions"`\n"PersonsByDistinctIdsInTeamResponse\x12:\n\x07results\x18\x01 \x03(\x0b2).personhog.types.v1.PersonWithDistinctIds"\x96\x01\n\x1eGetPersonsByDistinctIdsRequest\x12=\n\x11team_distinct_ids\x18\x01 \x03(\x0b2".personhog.types.v1.TeamDistinctId\x125\n\x0cread_options\x18\x02 \x01(\x0b2\x1f.personhog.types.v1.ReadOptions"]\n\x1cPersonsByDistinctIdsResponse\x12=\n\x07results\x18\x01 \x03(\x0b2,.personhog.types.v1.PersonWithTeamDistinctId"\x99\x01\n\x1eGetDistinctIdsForPersonRequest\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12\x11\n\tperson_id\x18\x02 \x01(\x03\x125\n\x0cread_options\x18\x03 \x01(\x0b2\x1f.personhog.types.v1.ReadOptions\x12\x12\n\x05limit\x18\x04 \x01(\x03H\x00\x88\x01\x01B\x08\n\x06_limit"b\n\x1fGetDistinctIdsForPersonResponse\x12?\n\x0cdistinct_ids\x18\x01 \x03(\x0b2).personhog.types.v1.DistinctIdWithVersion"\xb1\x01\n\x1fGetDistinctIdsForPersonsRequest\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12\x12\n\nperson_ids\x18\x02 \x03(\x03\x125\n\x0cread_options\x18\x03 \x01(\x0b2\x1f.personhog.types.v1.ReadOptions\x12\x1d\n\x10limit_per_person\x18\x04 \x01(\x03H\x00\x88\x01\x01B\x13\n\x11_limit_per_person"f\n GetDistinctIdsForPersonsResponse\x12B\n\x13person_distinct_ids\x18\x01 \x03(\x0b2%.personhog.types.v1.PersonDistinctIds"\xa6\x01\n\x1dUpdatePersonPropertiesRequest\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12\x11\n\tperson_id\x18\x02 \x01(\x03\x12\x12\n\nevent_name\x18\x03 \x01(\t\x12\x16\n\x0eset_properties\x18\x04 \x01(\x0c\x12\x1b\n\x13set_once_properties\x18\x05 \x01(\x0c\x12\x18\n\x10unset_properties\x18\x06 \x03(\t"m\n\x1eUpdatePersonPropertiesResponse\x12/\n\x06person\x18\x01 \x01(\x0b2\x1a.personhog.types.v1.PersonH\x00\x88\x01\x01\x12\x0f\n\x07updated\x18\x02 \x01(\x08B\t\n\x07_person")\n\x18AllocatePersonIdsRequest\x12\r\n\x05count\x18\x01 \x01(\r"/\n\x19AllocatePersonIdsResponse\x12\x12\n\nperson_ids\x18\x01 \x03(\x03"\x9c\x01\n\x13CreatePersonRequest\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12\x11\n\tperson_id\x18\x02 \x01(\x03\x12\x0c\n\x04uuid\x18\x03 \x01(\t\x12\x12\n\nproperties\x18\x04 \x01(\x0c\x12\x12\n\ncreated_at\x18\x05 \x01(\x03\x12\x15\n\ris_identified\x18\x06 \x01(\x08\x12\x14\n\x0cdistinct_ids\x18\x07 \x03(\t"B\n\x14CreatePersonResponse\x12*\n\x06person\x18\x01 \x01(\x0b2\x1a.personhog.types.v1.Person"=\n\x14DeletePersonsRequest\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12\x14\n\x0cperson_uuids\x18\x02 \x03(\t".\n\x15DeletePersonsResponse\x12\x15\n\rdeleted_count\x18\x01 \x01(\x03"G\n DeletePersonsBatchForTeamRequest\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12\x12\n\nbatch_size\x18\x02 \x01(\x03":\n!DeletePersonsBatchForTeamResponse\x12\x15\n\rdeleted_count\x18\x01 \x01(\x03"U\n.DeletePersonlessDistinctIdsBatchForTeamRequest\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12\x12\n\nbatch_size\x18\x02 \x01(\x03"H\n/DeletePersonlessDistinctIdsBatchForTeamResponse\x12\x15\n\rdeleted_count\x18\x01 \x01(\x03"W\n\x12SplitPersonRequest\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12\x11\n\tperson_id\x18\x02 \x01(\x03\x12\x1d\n\x15distinct_ids_to_split\x18\x03 \x03(\t"\x8e\x01\n\x0bSplitResult\x12\x13\n\x0bdistinct_id\x18\x01 \x01(\t\x12\x17\n\x0fnew_person_uuid\x18\x02 \x01(\t\x12\x1a\n\x12new_person_version\x18\x03 \x01(\x03\x12\x13\n\x0bpdi_version\x18\x04 \x01(\x03\x12 \n\x18new_person_created_at_ms\x18\x05 \x01(\x03"F\n\x13SplitPersonResponse\x12/\n\x06splits\x18\x01 \x03(\x0b2\x1f.personhog.types.v1.SplitResult"c\n&SetPersonDistinctIdVersionFloorRequest\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12\x13\n\x0bdistinct_id\x18\x02 \x01(\t\x12\x13\n\x0bmin_version\x18\x03 \x01(\x03"e\n\'SetPersonDistinctIdVersionFloorResponse\x12/\n\x06person\x18\x01 \x01(\x0b2\x1a.personhog.types.v1.PersonH\x00\x88\x01\x01B\t\n\x07_person"W\n\x1cSetPersonVersionFloorRequest\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12\x11\n\tperson_id\x18\x02 \x01(\x03\x12\x13\n\x0bmin_version\x18\x03 \x01(\x03"0\n\x1dSetPersonVersionFloorResponse\x12\x0f\n\x07updated\x18\x01 \x01(\x08b\x06proto3'
)
_globals = globals()
_builder.BuildMessageAndEnumDescriptors(DESCRIPTOR, _globals)
_builder.BuildTopDescriptorsAndMessages(DESCRIPTOR, "personhog.types.v1.person_pb2", _globals)
if not _descriptor._USE_C_DESCRIPTORS:
    DESCRIPTOR._loaded_options = None
    _globals["_PERSON"]._serialized_start = 89
    _globals["_PERSON"]._serialized_end = 448
    _globals["_DISTINCTIDWITHVERSION"]._serialized_start = 450
    _globals["_DISTINCTIDWITHVERSION"]._serialized_end = 528
    _globals["_PERSONWITHDISTINCTIDS"]._serialized_start = 530
    _globals["_PERSONWITHDISTINCTIDS"]._serialized_end = 634
    _globals["_PERSONDISTINCTIDS"]._serialized_start = 636
    _globals["_PERSONDISTINCTIDS"]._serialized_end = 739
    _globals["_PERSONWITHTEAMDISTINCTID"]._serialized_start = 742
    _globals["_PERSONWITHTEAMDISTINCTID"]._serialized_end = 877
    _globals["_GETPERSONREQUEST"]._serialized_start = 879
    _globals["_GETPERSONREQUEST"]._serialized_end = 988
    _globals["_GETPERSONRESPONSE"]._serialized_start = 990
    _globals["_GETPERSONRESPONSE"]._serialized_end = 1069
    _globals["_GETPERSONSREQUEST"]._serialized_start = 1071
    _globals["_GETPERSONSREQUEST"]._serialized_end = 1182
    _globals["_PERSONSRESPONSE"]._serialized_start = 1184
    _globals["_PERSONSRESPONSE"]._serialized_end = 1267
    _globals["_GETPERSONBYUUIDREQUEST"]._serialized_start = 1269
    _globals["_GETPERSONBYUUIDREQUEST"]._serialized_end = 1379
    _globals["_GETPERSONSBYUUIDSREQUEST"]._serialized_start = 1381
    _globals["_GETPERSONSBYUUIDSREQUEST"]._serialized_end = 1494
    _globals["_GETPERSONBYDISTINCTIDREQUEST"]._serialized_start = 1496
    _globals["_GETPERSONBYDISTINCTIDREQUEST"]._serialized_end = 1619
    _globals["_GETPERSONSBYDISTINCTIDSINTEAMREQUEST"]._serialized_start = 1622
    _globals["_GETPERSONSBYDISTINCTIDSINTEAMREQUEST"]._serialized_end = 1754
    _globals["_PERSONSBYDISTINCTIDSINTEAMRESPONSE"]._serialized_start = 1756
    _globals["_PERSONSBYDISTINCTIDSINTEAMRESPONSE"]._serialized_end = 1852
    _globals["_GETPERSONSBYDISTINCTIDSREQUEST"]._serialized_start = 1855
    _globals["_GETPERSONSBYDISTINCTIDSREQUEST"]._serialized_end = 2005
    _globals["_PERSONSBYDISTINCTIDSRESPONSE"]._serialized_start = 2007
    _globals["_PERSONSBYDISTINCTIDSRESPONSE"]._serialized_end = 2100
    _globals["_GETDISTINCTIDSFORPERSONREQUEST"]._serialized_start = 2103
    _globals["_GETDISTINCTIDSFORPERSONREQUEST"]._serialized_end = 2256
    _globals["_GETDISTINCTIDSFORPERSONRESPONSE"]._serialized_start = 2258
    _globals["_GETDISTINCTIDSFORPERSONRESPONSE"]._serialized_end = 2356
    _globals["_GETDISTINCTIDSFORPERSONSREQUEST"]._serialized_start = 2359
    _globals["_GETDISTINCTIDSFORPERSONSREQUEST"]._serialized_end = 2536
    _globals["_GETDISTINCTIDSFORPERSONSRESPONSE"]._serialized_start = 2538
    _globals["_GETDISTINCTIDSFORPERSONSRESPONSE"]._serialized_end = 2640
    _globals["_UPDATEPERSONPROPERTIESREQUEST"]._serialized_start = 2643
    _globals["_UPDATEPERSONPROPERTIESREQUEST"]._serialized_end = 2809
    _globals["_UPDATEPERSONPROPERTIESRESPONSE"]._serialized_start = 2811
    _globals["_UPDATEPERSONPROPERTIESRESPONSE"]._serialized_end = 2920
    _globals["_ALLOCATEPERSONIDSREQUEST"]._serialized_start = 2922
    _globals["_ALLOCATEPERSONIDSREQUEST"]._serialized_end = 2963
    _globals["_ALLOCATEPERSONIDSRESPONSE"]._serialized_start = 2965
    _globals["_ALLOCATEPERSONIDSRESPONSE"]._serialized_end = 3012
    _globals["_CREATEPERSONREQUEST"]._serialized_start = 3015
    _globals["_CREATEPERSONREQUEST"]._serialized_end = 3171
    _globals["_CREATEPERSONRESPONSE"]._serialized_start = 3173
    _globals["_CREATEPERSONRESPONSE"]._serialized_end = 3239
    _globals["_DELETEPERSONSREQUEST"]._serialized_start = 3241
    _globals["_DELETEPERSONSREQUEST"]._serialized_end = 3302
    _globals["_DELETEPERSONSRESPONSE"]._serialized_start = 3304
    _globals["_DELETEPERSONSRESPONSE"]._serialized_end = 3350
    _globals["_DELETEPERSONSBATCHFORTEAMREQUEST"]._serialized_start = 3352
    _globals["_DELETEPERSONSBATCHFORTEAMREQUEST"]._serialized_end = 3423
    _globals["_DELETEPERSONSBATCHFORTEAMRESPONSE"]._serialized_start = 3425
    _globals["_DELETEPERSONSBATCHFORTEAMRESPONSE"]._serialized_end = 3483
    _globals["_DELETEPERSONLESSDISTINCTIDSBATCHFORTEAMREQUEST"]._serialized_start = 3485
    _globals["_DELETEPERSONLESSDISTINCTIDSBATCHFORTEAMREQUEST"]._serialized_end = 3570
    _globals["_DELETEPERSONLESSDISTINCTIDSBATCHFORTEAMRESPONSE"]._serialized_start = 3572
    _globals["_DELETEPERSONLESSDISTINCTIDSBATCHFORTEAMRESPONSE"]._serialized_end = 3644
    _globals["_SPLITPERSONREQUEST"]._serialized_start = 3646
    _globals["_SPLITPERSONREQUEST"]._serialized_end = 3733
    _globals["_SPLITRESULT"]._serialized_start = 3736
    _globals["_SPLITRESULT"]._serialized_end = 3878
    _globals["_SPLITPERSONRESPONSE"]._serialized_start = 3880
    _globals["_SPLITPERSONRESPONSE"]._serialized_end = 3950
    _globals["_SETPERSONDISTINCTIDVERSIONFLOORREQUEST"]._serialized_start = 3952
    _globals["_SETPERSONDISTINCTIDVERSIONFLOORREQUEST"]._serialized_end = 4051
    _globals["_SETPERSONDISTINCTIDVERSIONFLOORRESPONSE"]._serialized_start = 4053
    _globals["_SETPERSONDISTINCTIDVERSIONFLOORRESPONSE"]._serialized_end = 4154
    _globals["_SETPERSONVERSIONFLOORREQUEST"]._serialized_start = 4156
    _globals["_SETPERSONVERSIONFLOORREQUEST"]._serialized_end = 4243
    _globals["_SETPERSONVERSIONFLOORRESPONSE"]._serialized_start = 4245
    _globals["_SETPERSONVERSIONFLOORRESPONSE"]._serialized_end = 4293
