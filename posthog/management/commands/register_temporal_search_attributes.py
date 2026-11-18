import logging

from django.conf import settings
from django.core.management.base import BaseCommand

import grpc
import structlog
import temporalio.api.enums.v1 as enums
import temporalio.api.operatorservice.v1 as ops
from temporalio.api.operatorservice.v1.service_pb2_grpc import OperatorServiceStub
from temporalio.common import SearchAttributeKey

from posthog.temporal.common.search_attributes import POSTHOG_SEARCH_ATTRIBUTES

logger = structlog.get_logger(__name__)

_RPC_TIMEOUT_SECONDS = 60

# Maps SearchAttributeKey value_type to the protobuf IndexedValueType enum
_TYPE_MAP: dict[type, enums.IndexedValueType.ValueType] = {
    int: enums.IndexedValueType.INDEXED_VALUE_TYPE_INT,
    str: enums.IndexedValueType.INDEXED_VALUE_TYPE_KEYWORD,
    float: enums.IndexedValueType.INDEXED_VALUE_TYPE_DOUBLE,
    bool: enums.IndexedValueType.INDEXED_VALUE_TYPE_BOOL,
}


def _resolve_type(key: SearchAttributeKey) -> enums.IndexedValueType.ValueType:
    value_type = _TYPE_MAP.get(key.value_type)
    if value_type is None:
        raise ValueError(f"Unsupported search attribute type: {key.value_type} for {key.name}")
    return value_type


# A plain gRPC channel, not the temporalio Client. The Client completes RPCs on Tokio threads. At exit, CPython
# can drop its Tokio runtime while one of those threads waits for the GIL, and the process then never exits
# (https://github.com/temporalio/sdk-python/issues/300 tracks the same race).
def _open_channel() -> grpc.Channel:
    target = f"{settings.TEMPORAL_HOST}:{settings.TEMPORAL_PORT}"
    if settings.TEMPORAL_CLIENT_CERT and settings.TEMPORAL_CLIENT_KEY:
        credentials = grpc.ssl_channel_credentials(
            private_key=settings.TEMPORAL_CLIENT_KEY.encode(),
            certificate_chain=settings.TEMPORAL_CLIENT_CERT.encode(),
        )
        return grpc.secure_channel(target, credentials)
    return grpc.insecure_channel(target)


def register_search_attributes(operator_service: OperatorServiceStub, namespace: str, dry_run: bool) -> None:
    # Match the Temporal SDK clients, which send the target namespace in this header on every request.
    rpc_metadata = (("temporal-namespace", namespace),)

    # List existing attributes
    resp = operator_service.ListSearchAttributes(
        ops.ListSearchAttributesRequest(namespace=namespace),
        timeout=_RPC_TIMEOUT_SECONDS,
        metadata=rpc_metadata,
    )
    existing = set(resp.custom_attributes.keys())

    # Find which ones need registering
    to_register = {}
    for key in POSTHOG_SEARCH_ATTRIBUTES:
        if key.name in existing:
            logger.info("Already registered", attribute=key.name)
        else:
            to_register[key.name] = _resolve_type(key)

    if not to_register:
        logger.info("All search attributes already registered")
        return

    if dry_run:
        for name, typ in to_register.items():
            logger.info("Would register", attribute=name, type=enums.IndexedValueType.Name(typ))
        return

    logger.info(f"Registering {len(to_register)} search attribute(s)", attributes=list(to_register.keys()))

    operator_service.AddSearchAttributes(
        ops.AddSearchAttributesRequest(namespace=namespace, search_attributes=to_register),
        timeout=_RPC_TIMEOUT_SECONDS,
        metadata=rpc_metadata,
    )

    logger.info("Done")


class Command(BaseCommand):
    help = "Register PostHog custom search attributes in Temporal"
    # A setup step in CI, dev runs and preview environments. The command never touches the ORM or the
    # URLconf, so the system checks only add startup time.
    requires_system_checks: list[str] = []

    def add_arguments(self, parser):
        parser.add_argument(
            "--namespace",
            default="default",
            help="Temporal namespace (default: 'default')",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Show what would be registered without making changes",
        )

    def handle(self, **options):
        logger.setLevel(logging.INFO)
        with _open_channel() as channel:
            register_search_attributes(OperatorServiceStub(channel), options["namespace"], options["dry_run"])
