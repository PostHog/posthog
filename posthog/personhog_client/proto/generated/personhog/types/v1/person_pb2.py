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
    b'\n\x1fpersonhog/types/v1/person.proto\x12\x12personhog.types.v1\x1a\x1fpersonhog/types/v1/common.proto"\xb2\x02\n\x06Person\x12\n\n\x02id\x18\x01 \x01(\x03\x12\x0c\n\x04uuid\x18\x02 \x01(\t\x12\x0f\n\x07team_id\x18\x03 \x01(\x03\x12\x12\n\nproperties\x18\x04 \x01(\x0c\x12"\n\x1aproperties_last_updated_at\x18\x05 \x01(\x0c\x12!\n\x19properties_last_operation\x18\x06 \x01(\x0c\x12\x12\n\ncreated_at\x18\x07 \x01(\x03\x12\x0f\n\x07version\x18\x08 \x01(\x03\x12\x15\n\ris_identified\x18\t \x01(\x08\x12\x17\n\nis_user_id\x18\n \x01(\x08H\x00\x88\x01\x01\x12\x19\n\x0clast_seen_at\x18\x0b \x01(\x03H\x01\x88\x01\x01\x12\x12\n\nis_deleted\x18\x0c \x01(\x08B\r\n\x0b_is_user_idB\x0f\n\r_last_seen_at"N\n\x15DistinctIdWithVersion\x12\x13\n\x0bdistinct_id\x18\x01 \x01(\t\x12\x14\n\x07version\x18\x02 \x01(\x03H\x00\x88\x01\x01B\n\n\x08_version"h\n\x15PersonWithDistinctIds\x12\x13\n\x0bdistinct_id\x18\x01 \x01(\t\x12/\n\x06person\x18\x02 \x01(\x0b2\x1a.personhog.types.v1.PersonH\x00\x88\x01\x01B\t\n\x07_person"g\n\x11PersonDistinctIds\x12\x11\n\tperson_id\x18\x01 \x01(\x03\x12?\n\x0cdistinct_ids\x18\x02 \x03(\x0b2).personhog.types.v1.DistinctIdWithVersion"\x87\x01\n\x18PersonWithTeamDistinctId\x12/\n\x03key\x18\x01 \x01(\x0b2".personhog.types.v1.TeamDistinctId\x12/\n\x06person\x18\x02 \x01(\x0b2\x1a.personhog.types.v1.PersonH\x00\x88\x01\x01B\t\n\x07_person"m\n\x10GetPersonRequest\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12\x11\n\tperson_id\x18\x02 \x01(\x03\x125\n\x0cread_options\x18\x03 \x01(\x0b2\x1f.personhog.types.v1.ReadOptions"O\n\x11GetPersonResponse\x12/\n\x06person\x18\x01 \x01(\x0b2\x1a.personhog.types.v1.PersonH\x00\x88\x01\x01B\t\n\x07_person"o\n\x11GetPersonsRequest\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12\x12\n\nperson_ids\x18\x02 \x03(\x03\x125\n\x0cread_options\x18\x03 \x01(\x0b2\x1f.personhog.types.v1.ReadOptions"S\n\x0fPersonsResponse\x12+\n\x07persons\x18\x01 \x03(\x0b2\x1a.personhog.types.v1.Person\x12\x13\n\x0bmissing_ids\x18\x02 \x03(\x03"n\n\x16GetPersonByUuidRequest\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12\x0c\n\x04uuid\x18\x02 \x01(\t\x125\n\x0cread_options\x18\x03 \x01(\x0b2\x1f.personhog.types.v1.ReadOptions"q\n\x18GetPersonsByUuidsRequest\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12\r\n\x05uuids\x18\x02 \x03(\t\x125\n\x0cread_options\x18\x03 \x01(\x0b2\x1f.personhog.types.v1.ReadOptions"{\n\x1cGetPersonByDistinctIdRequest\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12\x13\n\x0bdistinct_id\x18\x02 \x01(\t\x125\n\x0cread_options\x18\x03 \x01(\x0b2\x1f.personhog.types.v1.ReadOptions"\x84\x01\n$GetPersonsByDistinctIdsInTeamRequest\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12\x14\n\x0cdistinct_ids\x18\x02 \x03(\t\x125\n\x0cread_options\x18\x03 \x01(\x0b2\x1f.personhog.types.v1.ReadOptions"`\n"PersonsByDistinctIdsInTeamResponse\x12:\n\x07results\x18\x01 \x03(\x0b2).personhog.types.v1.PersonWithDistinctIds"\x96\x01\n\x1eGetPersonsByDistinctIdsRequest\x12=\n\x11team_distinct_ids\x18\x01 \x03(\x0b2".personhog.types.v1.TeamDistinctId\x125\n\x0cread_options\x18\x02 \x01(\x0b2\x1f.personhog.types.v1.ReadOptions"]\n\x1cPersonsByDistinctIdsResponse\x12=\n\x07results\x18\x01 \x03(\x0b2,.personhog.types.v1.PersonWithTeamDistinctId"\x99\x01\n\x1eGetDistinctIdsForPersonRequest\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12\x11\n\tperson_id\x18\x02 \x01(\x03\x125\n\x0cread_options\x18\x03 \x01(\x0b2\x1f.personhog.types.v1.ReadOptions\x12\x12\n\x05limit\x18\x04 \x01(\x03H\x00\x88\x01\x01B\x08\n\x06_limit"b\n\x1fGetDistinctIdsForPersonResponse\x12?\n\x0cdistinct_ids\x18\x01 \x03(\x0b2).personhog.types.v1.DistinctIdWithVersion"\xb1\x01\n\x1fGetDistinctIdsForPersonsRequest\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12\x12\n\nperson_ids\x18\x02 \x03(\x03\x125\n\x0cread_options\x18\x03 \x01(\x0b2\x1f.personhog.types.v1.ReadOptions\x12\x1d\n\x10limit_per_person\x18\x04 \x01(\x03H\x00\x88\x01\x01B\x13\n\x11_limit_per_person"f\n GetDistinctIdsForPersonsResponse\x12B\n\x13person_distinct_ids\x18\x01 \x03(\x0b2%.personhog.types.v1.PersonDistinctIds"\x80\x02\n\x1dUpdatePersonPropertiesRequest\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12\x11\n\tperson_id\x18\x02 \x01(\x03\x12\x12\n\nevent_name\x18\x03 \x01(\t\x12\x16\n\x0eset_properties\x18\x04 \x01(\x0c\x12\x1b\n\x13set_once_properties\x18\x05 \x01(\x0c\x12\x18\n\x10unset_properties\x18\x06 \x03(\t\x12\x1a\n\ris_identified\x18\x07 \x01(\x08H\x00\x88\x01\x01\x12\x19\n\x0clast_seen_at\x18\x08 \x01(\x03H\x01\x88\x01\x01B\x10\n\x0e_is_identifiedB\x0f\n\r_last_seen_at"m\n\x1eUpdatePersonPropertiesResponse\x12/\n\x06person\x18\x01 \x01(\x0b2\x1a.personhog.types.v1.PersonH\x00\x88\x01\x01\x12\x0f\n\x07updated\x18\x02 \x01(\x08B\t\n\x07_person"=\n\x14DeletePersonsRequest\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12\x14\n\x0cperson_uuids\x18\x02 \x03(\t".\n\x15DeletePersonsResponse\x12\x15\n\rdeleted_count\x18\x01 \x01(\x03"G\n DeletePersonsBatchForTeamRequest\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12\x12\n\nbatch_size\x18\x02 \x01(\x03":\n!DeletePersonsBatchForTeamResponse\x12\x15\n\rdeleted_count\x18\x01 \x01(\x03"W\n\x12SplitPersonRequest\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12\x11\n\tperson_id\x18\x02 \x01(\x03\x12\x1d\n\x15distinct_ids_to_split\x18\x03 \x03(\t"\x8e\x01\n\x0bSplitResult\x12\x13\n\x0bdistinct_id\x18\x01 \x01(\t\x12\x17\n\x0fnew_person_uuid\x18\x02 \x01(\t\x12\x1a\n\x12new_person_version\x18\x03 \x01(\x03\x12\x13\n\x0bpdi_version\x18\x04 \x01(\x03\x12 \n\x18new_person_created_at_ms\x18\x05 \x01(\x03"F\n\x13SplitPersonResponse\x12/\n\x06splits\x18\x01 \x03(\x0b2\x1f.personhog.types.v1.SplitResult"c\n&SetPersonDistinctIdVersionFloorRequest\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12\x13\n\x0bdistinct_id\x18\x02 \x01(\t\x12\x13\n\x0bmin_version\x18\x03 \x01(\x03"e\n\'SetPersonDistinctIdVersionFloorResponse\x12/\n\x06person\x18\x01 \x01(\x0b2\x1a.personhog.types.v1.PersonH\x00\x88\x01\x01B\t\n\x07_person"W\n\x1cSetPersonVersionFloorRequest\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12\x11\n\tperson_id\x18\x02 \x01(\x03\x12\x13\n\x0bmin_version\x18\x03 \x01(\x03"0\n\x1dSetPersonVersionFloorResponse\x12\x0f\n\x07updated\x18\x01 \x01(\x08"\x99\x01\n\x12FencePersonRequest\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12\x11\n\tperson_id\x18\x02 \x01(\x03\x12\r\n\x05op_id\x18\x03 \x01(\t\x124\n\x07op_type\x18\x04 \x01(\x0e2#.personhog.types.v1.LifecycleOpType\x12\x1a\n\x12creator_event_uuid\x18\x05 \x01(\t"A\n\x13FencePersonResponse\x12*\n\x06sealed\x18\x01 \x01(\x0b2\x1a.personhog.types.v1.Person"\xd6\x01\n\x13ReleaseFenceRequest\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12\x11\n\tperson_id\x18\x02 \x01(\x03\x12\x13\n\x0bperson_uuid\x18\x03 \x01(\t\x12\r\n\x05op_id\x18\x04 \x01(\t\x123\n\x07outcome\x18\x05 \x01(\x0e2".personhog.types.v1.ReleaseOutcome\x12\x1b\n\x0esealed_version\x18\x06 \x01(\x03H\x00\x88\x01\x01\x12\x12\n\ncreated_at\x18\x07 \x01(\x03B\x11\n\x0f_sealed_version"\x16\n\x14ReleaseFenceResponse"S\n\x14SealedSourceSnapshot\x12*\n\x06person\x18\x01 \x01(\x0b2\x1a.personhog.types.v1.Person\x12\x0f\n\x07ordinal\x18\x02 \x01(\x05"\xbd\x01\n\x19FoldPersonDocumentRequest\x12\x0f\n\x07team_id\x18\x01 \x01(\x03\x12\x11\n\tperson_id\x18\x02 \x01(\x03\x12B\n\x10sealed_snapshots\x18\x03 \x03(\x0b2(.personhog.types.v1.SealedSourceSnapshot\x12\x11\n\tevent_set\x18\x04 \x01(\x0c\x12\x16\n\x0eevent_set_once\x18\x05 \x01(\x0c\x12\r\n\x05op_id\x18\x06 \x01(\t"H\n\x1aFoldPersonDocumentResponse\x12*\n\x06person\x18\x01 \x01(\x0b2\x1a.personhog.types.v1.Person*o\n\x0fLifecycleOpType\x12!\n\x1dLIFECYCLE_OP_TYPE_UNSPECIFIED\x10\x00\x12\x1c\n\x18LIFECYCLE_OP_TYPE_DELETE\x10\x01\x12\x1b\n\x17LIFECYCLE_OP_TYPE_MERGE\x10\x02*m\n\x0eReleaseOutcome\x12\x1f\n\x1bRELEASE_OUTCOME_UNSPECIFIED\x10\x00\x12\x1d\n\x19RELEASE_OUTCOME_COMMITTED\x10\x01\x12\x1b\n\x17RELEASE_OUTCOME_ABORTED\x10\x02b\x06proto3'
)
_globals = globals()
_builder.BuildMessageAndEnumDescriptors(DESCRIPTOR, _globals)
_builder.BuildTopDescriptorsAndMessages(DESCRIPTOR, "personhog.types.v1.person_pb2", _globals)
if not _descriptor._USE_C_DESCRIPTORS:
    DESCRIPTOR._loaded_options = None
    _globals["_LIFECYCLEOPTYPE"]._serialized_start = 4667
    _globals["_LIFECYCLEOPTYPE"]._serialized_end = 4778
    _globals["_RELEASEOUTCOME"]._serialized_start = 4780
    _globals["_RELEASEOUTCOME"]._serialized_end = 4889
    _globals["_PERSON"]._serialized_start = 89
    _globals["_PERSON"]._serialized_end = 395
    _globals["_DISTINCTIDWITHVERSION"]._serialized_start = 397
    _globals["_DISTINCTIDWITHVERSION"]._serialized_end = 475
    _globals["_PERSONWITHDISTINCTIDS"]._serialized_start = 477
    _globals["_PERSONWITHDISTINCTIDS"]._serialized_end = 581
    _globals["_PERSONDISTINCTIDS"]._serialized_start = 583
    _globals["_PERSONDISTINCTIDS"]._serialized_end = 686
    _globals["_PERSONWITHTEAMDISTINCTID"]._serialized_start = 689
    _globals["_PERSONWITHTEAMDISTINCTID"]._serialized_end = 824
    _globals["_GETPERSONREQUEST"]._serialized_start = 826
    _globals["_GETPERSONREQUEST"]._serialized_end = 935
    _globals["_GETPERSONRESPONSE"]._serialized_start = 937
    _globals["_GETPERSONRESPONSE"]._serialized_end = 1016
    _globals["_GETPERSONSREQUEST"]._serialized_start = 1018
    _globals["_GETPERSONSREQUEST"]._serialized_end = 1129
    _globals["_PERSONSRESPONSE"]._serialized_start = 1131
    _globals["_PERSONSRESPONSE"]._serialized_end = 1214
    _globals["_GETPERSONBYUUIDREQUEST"]._serialized_start = 1216
    _globals["_GETPERSONBYUUIDREQUEST"]._serialized_end = 1326
    _globals["_GETPERSONSBYUUIDSREQUEST"]._serialized_start = 1328
    _globals["_GETPERSONSBYUUIDSREQUEST"]._serialized_end = 1441
    _globals["_GETPERSONBYDISTINCTIDREQUEST"]._serialized_start = 1443
    _globals["_GETPERSONBYDISTINCTIDREQUEST"]._serialized_end = 1566
    _globals["_GETPERSONSBYDISTINCTIDSINTEAMREQUEST"]._serialized_start = 1569
    _globals["_GETPERSONSBYDISTINCTIDSINTEAMREQUEST"]._serialized_end = 1701
    _globals["_PERSONSBYDISTINCTIDSINTEAMRESPONSE"]._serialized_start = 1703
    _globals["_PERSONSBYDISTINCTIDSINTEAMRESPONSE"]._serialized_end = 1799
    _globals["_GETPERSONSBYDISTINCTIDSREQUEST"]._serialized_start = 1802
    _globals["_GETPERSONSBYDISTINCTIDSREQUEST"]._serialized_end = 1952
    _globals["_PERSONSBYDISTINCTIDSRESPONSE"]._serialized_start = 1954
    _globals["_PERSONSBYDISTINCTIDSRESPONSE"]._serialized_end = 2047
    _globals["_GETDISTINCTIDSFORPERSONREQUEST"]._serialized_start = 2050
    _globals["_GETDISTINCTIDSFORPERSONREQUEST"]._serialized_end = 2203
    _globals["_GETDISTINCTIDSFORPERSONRESPONSE"]._serialized_start = 2205
    _globals["_GETDISTINCTIDSFORPERSONRESPONSE"]._serialized_end = 2303
    _globals["_GETDISTINCTIDSFORPERSONSREQUEST"]._serialized_start = 2306
    _globals["_GETDISTINCTIDSFORPERSONSREQUEST"]._serialized_end = 2483
    _globals["_GETDISTINCTIDSFORPERSONSRESPONSE"]._serialized_start = 2485
    _globals["_GETDISTINCTIDSFORPERSONSRESPONSE"]._serialized_end = 2587
    _globals["_UPDATEPERSONPROPERTIESREQUEST"]._serialized_start = 2590
    _globals["_UPDATEPERSONPROPERTIESREQUEST"]._serialized_end = 2846
    _globals["_UPDATEPERSONPROPERTIESRESPONSE"]._serialized_start = 2848
    _globals["_UPDATEPERSONPROPERTIESRESPONSE"]._serialized_end = 2957
    _globals["_DELETEPERSONSREQUEST"]._serialized_start = 2959
    _globals["_DELETEPERSONSREQUEST"]._serialized_end = 3020
    _globals["_DELETEPERSONSRESPONSE"]._serialized_start = 3022
    _globals["_DELETEPERSONSRESPONSE"]._serialized_end = 3068
    _globals["_DELETEPERSONSBATCHFORTEAMREQUEST"]._serialized_start = 3070
    _globals["_DELETEPERSONSBATCHFORTEAMREQUEST"]._serialized_end = 3141
    _globals["_DELETEPERSONSBATCHFORTEAMRESPONSE"]._serialized_start = 3143
    _globals["_DELETEPERSONSBATCHFORTEAMRESPONSE"]._serialized_end = 3201
    _globals["_SPLITPERSONREQUEST"]._serialized_start = 3203
    _globals["_SPLITPERSONREQUEST"]._serialized_end = 3290
    _globals["_SPLITRESULT"]._serialized_start = 3293
    _globals["_SPLITRESULT"]._serialized_end = 3435
    _globals["_SPLITPERSONRESPONSE"]._serialized_start = 3437
    _globals["_SPLITPERSONRESPONSE"]._serialized_end = 3507
    _globals["_SETPERSONDISTINCTIDVERSIONFLOORREQUEST"]._serialized_start = 3509
    _globals["_SETPERSONDISTINCTIDVERSIONFLOORREQUEST"]._serialized_end = 3608
    _globals["_SETPERSONDISTINCTIDVERSIONFLOORRESPONSE"]._serialized_start = 3610
    _globals["_SETPERSONDISTINCTIDVERSIONFLOORRESPONSE"]._serialized_end = 3711
    _globals["_SETPERSONVERSIONFLOORREQUEST"]._serialized_start = 3713
    _globals["_SETPERSONVERSIONFLOORREQUEST"]._serialized_end = 3800
    _globals["_SETPERSONVERSIONFLOORRESPONSE"]._serialized_start = 3802
    _globals["_SETPERSONVERSIONFLOORRESPONSE"]._serialized_end = 3850
    _globals["_FENCEPERSONREQUEST"]._serialized_start = 3853
    _globals["_FENCEPERSONREQUEST"]._serialized_end = 4006
    _globals["_FENCEPERSONRESPONSE"]._serialized_start = 4008
    _globals["_FENCEPERSONRESPONSE"]._serialized_end = 4073
    _globals["_RELEASEFENCEREQUEST"]._serialized_start = 4076
    _globals["_RELEASEFENCEREQUEST"]._serialized_end = 4290
    _globals["_RELEASEFENCERESPONSE"]._serialized_start = 4292
    _globals["_RELEASEFENCERESPONSE"]._serialized_end = 4314
    _globals["_SEALEDSOURCESNAPSHOT"]._serialized_start = 4316
    _globals["_SEALEDSOURCESNAPSHOT"]._serialized_end = 4399
    _globals["_FOLDPERSONDOCUMENTREQUEST"]._serialized_start = 4402
    _globals["_FOLDPERSONDOCUMENTREQUEST"]._serialized_end = 4591
    _globals["_FOLDPERSONDOCUMENTRESPONSE"]._serialized_start = 4593
    _globals["_FOLDPERSONDOCUMENTRESPONSE"]._serialized_end = 4665
