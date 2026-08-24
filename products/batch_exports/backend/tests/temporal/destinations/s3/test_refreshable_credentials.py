import typing
import datetime as dt
import collections.abc

import pytest

import aioboto3
from aiobotocore.credentials import AioRefreshableCredentials
from botocore.credentials import ReadOnlyCredentials

from products.batch_exports.backend.service import AWSCredentials
from products.batch_exports.backend.temporal.destinations.s3_batch_export import (
    RefreshCoroutine,
    get_refreshable_session,
)

pytestmark = [pytest.mark.asyncio]


def make_refresh_stub(refreshed: AWSCredentials) -> tuple[list[int], RefreshCoroutine]:
    calls: list[int] = []

    async def refresh() -> AWSCredentials:
        calls.append(1)
        return refreshed

    return calls, refresh


async def get_frozen_session_credentials(session: aioboto3.Session) -> ReadOnlyCredentials:
    # aioboto3 sessions return a coroutine at runtime, but the stubs carry boto3's sync signature.
    credentials = await typing.cast(collections.abc.Awaitable[AioRefreshableCredentials], session.get_credentials())
    return await credentials.get_frozen_credentials()


async def test_get_refreshable_session_refreshes_expired_credentials():
    now = dt.datetime.now(dt.UTC)
    initial = AWSCredentials(
        aws_access_key_id="initial-key",
        aws_secret_access_key="initial-secret",
        aws_session_token="initial-token",
        expiration=now - dt.timedelta(minutes=5),
    )
    refreshed = AWSCredentials(
        aws_access_key_id="refreshed-key",
        aws_secret_access_key="refreshed-secret",
        aws_session_token="refreshed-token",
        expiration=now + dt.timedelta(hours=1),
    )
    calls, refresh = make_refresh_stub(refreshed)

    session = get_refreshable_session(initial, refresh)
    frozen = await get_frozen_session_credentials(session)

    assert len(calls) == 1
    assert frozen.access_key == "refreshed-key"
    assert frozen.secret_key == "refreshed-secret"
    assert frozen.token == "refreshed-token"


async def test_get_refreshable_session_does_not_refresh_valid_credentials():
    now = dt.datetime.now(dt.UTC)
    initial = AWSCredentials(
        aws_access_key_id="initial-key",
        aws_secret_access_key="initial-secret",
        aws_session_token="initial-token",
        expiration=now + dt.timedelta(hours=1),
    )
    calls, refresh = make_refresh_stub(initial)

    session = get_refreshable_session(initial, refresh)
    frozen = await get_frozen_session_credentials(session)

    assert len(calls) == 0
    assert frozen.access_key == "initial-key"
    assert frozen.secret_key == "initial-secret"
    assert frozen.token == "initial-token"
