from datetime import UTC, datetime

import pytest
from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from products.customer_analytics.backend.logic.account_property_sync import (
    AccountPropertySyncSegment,
    _mark_completed_and_maybe_cleanup,
    _matching_account_ids,
    _value_hash,
)
from products.customer_analytics.backend.models.team_scoped_test_base import TeamScopedTestMixin
from products.customer_analytics.backend.test.factories import create_account
from products.warehouse_sources.backend.facade.hooks import saved_query_binding
from products.warehouse_sources.backend.facade.temporal import account_property_job_staged_prefix

_MODULE = "products.customer_analytics.backend.logic.account_property_sync"


class AccountPropertySegmentTest(TeamScopedTestMixin, BaseTest):
    def test_segments_tracked_and_ignored_accounts_and_excludes_churned_accounts(self) -> None:
        tracked = create_account(team_id=self.team.id, external_id="tracked")
        ignored = create_account(team_id=self.team.id, external_id="ignored", ignored_at=datetime.now(UTC))
        create_account(team_id=self.team.id, external_id="churned", churned_at=datetime.now(UTC))

        tracked_matches = _matching_account_ids(
            self.team.id,
            AccountPropertySyncSegment.TRACKED,
            ["tracked", "ignored", "churned"],
        )
        ignored_matches = _matching_account_ids(
            self.team.id,
            AccountPropertySyncSegment.IGNORED,
            ["tracked", "ignored", "churned"],
        )

        assert tracked_matches == {"tracked": tracked.id}
        assert ignored_matches == {"ignored": ignored.id}

    def test_value_hash_is_stable_for_equivalent_values(self) -> None:
        assert _value_hash({"a": 1, "b": [2, 3]}) == _value_hash({"b": [2, 3], "a": 1})


class _S3ClientContext:
    def __init__(self, client: MagicMock) -> None:
        self.client = client

    async def __aenter__(self) -> MagicMock:
        return self.client

    async def __aexit__(self, *args) -> bool:
        return False


@pytest.mark.asyncio
async def test_staged_parquet_is_deleted_only_after_both_segments_complete() -> None:
    binding = saved_query_binding("019f0000-0000-7000-8000-000000000001")
    client = MagicMock()
    client._pipe_file = AsyncMock()
    client._rm = AsyncMock()
    client._ls = AsyncMock(
        side_effect=[
            [{"Key": "prefix/tracked.done", "type": "file"}],
            [
                {"Key": "prefix/tracked.done", "type": "file"},
                {"Key": "prefix/ignored.done", "type": "file"},
            ],
        ]
    )

    with patch(f"{_MODULE}.aget_s3_client", return_value=_S3ClientContext(client)):
        await _mark_completed_and_maybe_cleanup(7, binding, "job-1", AccountPropertySyncSegment.TRACKED)
        client._rm.assert_not_awaited()
        await _mark_completed_and_maybe_cleanup(7, binding, "job-1", AccountPropertySyncSegment.IGNORED)

    client._rm.assert_awaited_once_with(
        f"s3://{account_property_job_staged_prefix(7, binding, 'job-1')}/",
        recursive=True,
    )
