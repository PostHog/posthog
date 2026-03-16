import asyncio
import logging

from django.core.management.base import BaseCommand

import structlog
import temporalio.api.enums.v1 as enums
import temporalio.api.operatorservice.v1 as ops
from temporalio.common import SearchAttributeKey

from posthog.temporal.common.client import async_connect
from posthog.temporal.common.search_attributes import POSTHOG_SEARCH_ATTRIBUTES

logger = structlog.get_logger(__name__)

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


class Command(BaseCommand):
    help = "Register PostHog custom search attributes in Temporal"

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
        asyncio.run(self._run(options))

    async def _run(self, options):
        namespace = options["namespace"]
        dry_run = options["dry_run"]
        temporal = await async_connect()

        # List existing attributes
        resp = await temporal.operator_service.list_search_attributes(
            ops.ListSearchAttributesRequest(namespace=namespace)
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

        await temporal.operator_service.add_search_attributes(
            ops.AddSearchAttributesRequest(
                namespace=namespace,
                search_attributes=to_register,
            )
        )

        logger.info("Done")
