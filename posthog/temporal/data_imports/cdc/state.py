"""Persisted CDC runtime state.

`ExternalDataSource.cdc_state` is a plain (unencrypted, queryable) JSON column holding runtime
CDC signals — lag snapshots, last-extraction heartbeat, broken/paused flags — so the sweeper,
health checks, and API can read them without opening a live replication connection. Multiple
writers race (the hourly sweeper vs. per-run extraction vs. API actions), so every update is a
read-modify-write under a row lock to avoid lost updates.
"""

from __future__ import annotations

import uuid
import typing

from django.db import transaction

from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource


def update_cdc_state(source_id: uuid.UUID | str, **fields: typing.Any) -> dict[str, typing.Any]:
    """Merge `fields` into `source.cdc_state` under a row lock; return the merged dict.

    Read-modify-write on the same JSON blob, so concurrent writers (sweeper, extraction, API)
    must serialize or they clobber each other's keys.
    """
    with transaction.atomic():
        # `of=("self",)` locks only the source row; the default manager applies
        # select_related("revenue_analytics_config"), which we have no reason to lock here.
        source = ExternalDataSource.objects.select_for_update(of=("self",)).get(pk=source_id)
        state = dict(source.cdc_state or {})
        state.update(fields)
        source.cdc_state = state
        source.save(update_fields=["cdc_state", "updated_at"])
    return state
