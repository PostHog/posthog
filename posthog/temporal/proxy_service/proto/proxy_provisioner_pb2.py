# -*- coding: utf-8 -*-
# manually copied from github.com/posthog/proxy-provisioner@6b0fc2d
# ruff: noqa
# type: ignore
# Generated by the protocol buffer compiler.  DO NOT EDIT!
# source: proto/proxy-provisioner.proto
"""Generated protocol buffer code."""

from google.protobuf.internal import builder as _builder
from google.protobuf import descriptor as _descriptor
from google.protobuf import descriptor_pool as _descriptor_pool
from google.protobuf import symbol_database as _symbol_database

# @@protoc_insertion_point(imports)

_sym_db = _symbol_database.Default()


DESCRIPTOR = _descriptor_pool.Default().AddSerializedFile(
    b'\n\x1dproto/proxy-provisioner.proto\x12\x0bprovisioner"-\n\rCreateRequest\x12\x0c\n\x04uuid\x18\x01 \x01(\t\x12\x0e\n\x06\x64omain\x18\x02 \x01(\t"\x10\n\x0e\x43reateResponse"-\n\rStatusRequest\x12\x0c\n\x04uuid\x18\x01 \x01(\t\x12\x0e\n\x06\x64omain\x18\x02 \x01(\t"K\n\x0eStatusResponse\x12\x39\n\x12\x63\x65rtificate_status\x18\x01 \x01(\x0e\x32\x1d.provisioner.CertificateState"-\n\rDeleteRequest\x12\x0c\n\x04uuid\x18\x01 \x01(\t\x12\x0e\n\x06\x64omain\x18\x02 \x01(\t"\x10\n\x0e\x44\x65leteResponse"H\n\x0eResponseStatus\x12%\n\x05\x65rror\x18\x01 \x01(\x0e\x32\x16.provisioner.ErrorType\x12\x0f\n\x07message\x18\x02 \x01(\t*7\n\x10\x43\x65rtificateState\x12\x0b\n\x07UNKNOWN\x10\x00\x12\x0b\n\x07ISSUING\x10\x01\x12\t\n\x05READY\x10\x02*^\n\tErrorType\x12\x06\n\x02OK\x10\x00\x12\x11\n\rUNKNOWN_ERROR\x10\x01\x12\x13\n\x0fINVALID_REQUEST\x10\x02\x12\r\n\tNOT_FOUND\x10\x03\x12\x12\n\x0eINTERNAL_ERROR\x10\x04\x32\xe2\x01\n\x17ProxyProvisionerService\x12\x41\n\x06\x43reate\x12\x1a.provisioner.CreateRequest\x1a\x1b.provisioner.CreateResponse\x12\x41\n\x06Status\x12\x1a.provisioner.StatusRequest\x1a\x1b.provisioner.StatusResponse\x12\x41\n\x06\x44\x65lete\x12\x1a.provisioner.DeleteRequest\x1a\x1b.provisioner.DeleteResponseB\x11Z\x0fpkg/provisionerb\x06proto3'
)

_builder.BuildMessageAndEnumDescriptors(DESCRIPTOR, globals())
_builder.BuildTopDescriptorsAndMessages(DESCRIPTOR, "proto.proxy_provisioner_pb2", globals())
if _descriptor._USE_C_DESCRIPTORS == False:
    DESCRIPTOR._options = None
    DESCRIPTOR._serialized_options = b"Z\017pkg/provisioner"
    _CERTIFICATESTATE._serialized_start = 374
    _CERTIFICATESTATE._serialized_end = 429
    _ERRORTYPE._serialized_start = 431
    _ERRORTYPE._serialized_end = 525
    _CREATEREQUEST._serialized_start = 46
    _CREATEREQUEST._serialized_end = 91
    _CREATERESPONSE._serialized_start = 93
    _CREATERESPONSE._serialized_end = 109
    _STATUSREQUEST._serialized_start = 111
    _STATUSREQUEST._serialized_end = 156
    _STATUSRESPONSE._serialized_start = 158
    _STATUSRESPONSE._serialized_end = 233
    _DELETEREQUEST._serialized_start = 235
    _DELETEREQUEST._serialized_end = 280
    _DELETERESPONSE._serialized_start = 282
    _DELETERESPONSE._serialized_end = 298
    _RESPONSESTATUS._serialized_start = 300
    _RESPONSESTATUS._serialized_end = 372
    _PROXYPROVISIONERSERVICE._serialized_start = 528
    _PROXYPROVISIONERSERVICE._serialized_end = 754
# @@protoc_insertion_point(module_scope)
