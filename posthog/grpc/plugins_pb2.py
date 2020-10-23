# -*- coding: utf-8 -*-
# Generated by the protocol buffer compiler.  DO NOT EDIT!
# source: posthog/grpc/plugins.proto
"""Generated protocol buffer code."""
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from google.protobuf import reflection as _reflection
from google.protobuf import symbol_database as _symbol_database

# @@protoc_insertion_point(imports)

_sym_db = _symbol_database.Default()


from google.protobuf import struct_pb2 as google_dot_protobuf_dot_struct__pb2

DESCRIPTOR = _descriptor.FileDescriptor(
    name="posthog/grpc/plugins.proto",
    package="",
    syntax="proto3",
    serialized_options=None,
    create_key=_descriptor._internal_create_key,
    serialized_pb=b'\n\x1aposthog/grpc/plugins.proto\x1a\x1cgoogle/protobuf/struct.proto"\x07\n\x05\x45mpty"\xa1\x01\n\x0cPosthogEvent\x12\n\n\x02ip\x18\x01 \x01(\t\x12\x10\n\x08site_url\x18\x02 \x01(\t\x12\r\n\x05\x65vent\x18\x03 \x01(\t\x12\x13\n\x0b\x64istinct_id\x18\x04 \x01(\t\x12\x0f\n\x07team_id\x18\x05 \x01(\x04\x12+\n\nproperties\x18\x06 \x01(\x0b\x32\x17.google.protobuf.Struct\x12\x11\n\ttimestamp\x18\x07 \x01(\t".\n\x0e\x43\x61ptureRequest\x12\x1c\n\x05\x65vent\x18\x01 \x01(\x0b\x32\r.PosthogEvent",\n\x0c\x43\x61ptureReply\x12\x1c\n\x05\x65vent\x18\x01 \x01(\x0b\x32\r.PosthogEvent2>\n\rPluginService\x12-\n\tOnCapture\x12\x0f.CaptureRequest\x1a\r.CaptureReply"\x00\x62\x06proto3',
    dependencies=[google_dot_protobuf_dot_struct__pb2.DESCRIPTOR,],
)


_EMPTY = _descriptor.Descriptor(
    name="Empty",
    full_name="Empty",
    filename=None,
    file=DESCRIPTOR,
    containing_type=None,
    create_key=_descriptor._internal_create_key,
    fields=[],
    extensions=[],
    nested_types=[],
    enum_types=[],
    serialized_options=None,
    is_extendable=False,
    syntax="proto3",
    extension_ranges=[],
    oneofs=[],
    serialized_start=60,
    serialized_end=67,
)


_POSTHOGEVENT = _descriptor.Descriptor(
    name="PosthogEvent",
    full_name="PosthogEvent",
    filename=None,
    file=DESCRIPTOR,
    containing_type=None,
    create_key=_descriptor._internal_create_key,
    fields=[
        _descriptor.FieldDescriptor(
            name="ip",
            full_name="PosthogEvent.ip",
            index=0,
            number=1,
            type=9,
            cpp_type=9,
            label=1,
            has_default_value=False,
            default_value=b"".decode("utf-8"),
            message_type=None,
            enum_type=None,
            containing_type=None,
            is_extension=False,
            extension_scope=None,
            serialized_options=None,
            file=DESCRIPTOR,
            create_key=_descriptor._internal_create_key,
        ),
        _descriptor.FieldDescriptor(
            name="site_url",
            full_name="PosthogEvent.site_url",
            index=1,
            number=2,
            type=9,
            cpp_type=9,
            label=1,
            has_default_value=False,
            default_value=b"".decode("utf-8"),
            message_type=None,
            enum_type=None,
            containing_type=None,
            is_extension=False,
            extension_scope=None,
            serialized_options=None,
            file=DESCRIPTOR,
            create_key=_descriptor._internal_create_key,
        ),
        _descriptor.FieldDescriptor(
            name="event",
            full_name="PosthogEvent.event",
            index=2,
            number=3,
            type=9,
            cpp_type=9,
            label=1,
            has_default_value=False,
            default_value=b"".decode("utf-8"),
            message_type=None,
            enum_type=None,
            containing_type=None,
            is_extension=False,
            extension_scope=None,
            serialized_options=None,
            file=DESCRIPTOR,
            create_key=_descriptor._internal_create_key,
        ),
        _descriptor.FieldDescriptor(
            name="distinct_id",
            full_name="PosthogEvent.distinct_id",
            index=3,
            number=4,
            type=9,
            cpp_type=9,
            label=1,
            has_default_value=False,
            default_value=b"".decode("utf-8"),
            message_type=None,
            enum_type=None,
            containing_type=None,
            is_extension=False,
            extension_scope=None,
            serialized_options=None,
            file=DESCRIPTOR,
            create_key=_descriptor._internal_create_key,
        ),
        _descriptor.FieldDescriptor(
            name="team_id",
            full_name="PosthogEvent.team_id",
            index=4,
            number=5,
            type=4,
            cpp_type=4,
            label=1,
            has_default_value=False,
            default_value=0,
            message_type=None,
            enum_type=None,
            containing_type=None,
            is_extension=False,
            extension_scope=None,
            serialized_options=None,
            file=DESCRIPTOR,
            create_key=_descriptor._internal_create_key,
        ),
        _descriptor.FieldDescriptor(
            name="properties",
            full_name="PosthogEvent.properties",
            index=5,
            number=6,
            type=11,
            cpp_type=10,
            label=1,
            has_default_value=False,
            default_value=None,
            message_type=None,
            enum_type=None,
            containing_type=None,
            is_extension=False,
            extension_scope=None,
            serialized_options=None,
            file=DESCRIPTOR,
            create_key=_descriptor._internal_create_key,
        ),
        _descriptor.FieldDescriptor(
            name="timestamp",
            full_name="PosthogEvent.timestamp",
            index=6,
            number=7,
            type=9,
            cpp_type=9,
            label=1,
            has_default_value=False,
            default_value=b"".decode("utf-8"),
            message_type=None,
            enum_type=None,
            containing_type=None,
            is_extension=False,
            extension_scope=None,
            serialized_options=None,
            file=DESCRIPTOR,
            create_key=_descriptor._internal_create_key,
        ),
    ],
    extensions=[],
    nested_types=[],
    enum_types=[],
    serialized_options=None,
    is_extendable=False,
    syntax="proto3",
    extension_ranges=[],
    oneofs=[],
    serialized_start=70,
    serialized_end=231,
)


_CAPTUREREQUEST = _descriptor.Descriptor(
    name="CaptureRequest",
    full_name="CaptureRequest",
    filename=None,
    file=DESCRIPTOR,
    containing_type=None,
    create_key=_descriptor._internal_create_key,
    fields=[
        _descriptor.FieldDescriptor(
            name="event",
            full_name="CaptureRequest.event",
            index=0,
            number=1,
            type=11,
            cpp_type=10,
            label=1,
            has_default_value=False,
            default_value=None,
            message_type=None,
            enum_type=None,
            containing_type=None,
            is_extension=False,
            extension_scope=None,
            serialized_options=None,
            file=DESCRIPTOR,
            create_key=_descriptor._internal_create_key,
        ),
    ],
    extensions=[],
    nested_types=[],
    enum_types=[],
    serialized_options=None,
    is_extendable=False,
    syntax="proto3",
    extension_ranges=[],
    oneofs=[],
    serialized_start=233,
    serialized_end=279,
)


_CAPTUREREPLY = _descriptor.Descriptor(
    name="CaptureReply",
    full_name="CaptureReply",
    filename=None,
    file=DESCRIPTOR,
    containing_type=None,
    create_key=_descriptor._internal_create_key,
    fields=[
        _descriptor.FieldDescriptor(
            name="event",
            full_name="CaptureReply.event",
            index=0,
            number=1,
            type=11,
            cpp_type=10,
            label=1,
            has_default_value=False,
            default_value=None,
            message_type=None,
            enum_type=None,
            containing_type=None,
            is_extension=False,
            extension_scope=None,
            serialized_options=None,
            file=DESCRIPTOR,
            create_key=_descriptor._internal_create_key,
        ),
    ],
    extensions=[],
    nested_types=[],
    enum_types=[],
    serialized_options=None,
    is_extendable=False,
    syntax="proto3",
    extension_ranges=[],
    oneofs=[],
    serialized_start=281,
    serialized_end=325,
)

_POSTHOGEVENT.fields_by_name["properties"].message_type = google_dot_protobuf_dot_struct__pb2._STRUCT
_CAPTUREREQUEST.fields_by_name["event"].message_type = _POSTHOGEVENT
_CAPTUREREPLY.fields_by_name["event"].message_type = _POSTHOGEVENT
DESCRIPTOR.message_types_by_name["Empty"] = _EMPTY
DESCRIPTOR.message_types_by_name["PosthogEvent"] = _POSTHOGEVENT
DESCRIPTOR.message_types_by_name["CaptureRequest"] = _CAPTUREREQUEST
DESCRIPTOR.message_types_by_name["CaptureReply"] = _CAPTUREREPLY
_sym_db.RegisterFileDescriptor(DESCRIPTOR)

Empty = _reflection.GeneratedProtocolMessageType(
    "Empty",
    (_message.Message,),
    {
        "DESCRIPTOR": _EMPTY,
        "__module__": "posthog.grpc.plugins_pb2"
        # @@protoc_insertion_point(class_scope:Empty)
    },
)
_sym_db.RegisterMessage(Empty)

PosthogEvent = _reflection.GeneratedProtocolMessageType(
    "PosthogEvent",
    (_message.Message,),
    {
        "DESCRIPTOR": _POSTHOGEVENT,
        "__module__": "posthog.grpc.plugins_pb2"
        # @@protoc_insertion_point(class_scope:PosthogEvent)
    },
)
_sym_db.RegisterMessage(PosthogEvent)

CaptureRequest = _reflection.GeneratedProtocolMessageType(
    "CaptureRequest",
    (_message.Message,),
    {
        "DESCRIPTOR": _CAPTUREREQUEST,
        "__module__": "posthog.grpc.plugins_pb2"
        # @@protoc_insertion_point(class_scope:CaptureRequest)
    },
)
_sym_db.RegisterMessage(CaptureRequest)

CaptureReply = _reflection.GeneratedProtocolMessageType(
    "CaptureReply",
    (_message.Message,),
    {
        "DESCRIPTOR": _CAPTUREREPLY,
        "__module__": "posthog.grpc.plugins_pb2"
        # @@protoc_insertion_point(class_scope:CaptureReply)
    },
)
_sym_db.RegisterMessage(CaptureReply)


_PLUGINSERVICE = _descriptor.ServiceDescriptor(
    name="PluginService",
    full_name="PluginService",
    file=DESCRIPTOR,
    index=0,
    serialized_options=None,
    create_key=_descriptor._internal_create_key,
    serialized_start=327,
    serialized_end=389,
    methods=[
        _descriptor.MethodDescriptor(
            name="OnCapture",
            full_name="PluginService.OnCapture",
            index=0,
            containing_service=None,
            input_type=_CAPTUREREQUEST,
            output_type=_CAPTUREREPLY,
            serialized_options=None,
            create_key=_descriptor._internal_create_key,
        ),
    ],
)
_sym_db.RegisterServiceDescriptor(_PLUGINSERVICE)

DESCRIPTOR.services_by_name["PluginService"] = _PLUGINSERVICE

# @@protoc_insertion_point(module_scope)
