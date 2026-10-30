import hashlib
from datetime import UTC, datetime, timedelta
from typing import Protocol, TypedDict, cast

import boto3
from botocore.config import Config

from posthog.dataclasses import frozen

from products.ai_training.backend.models import AITrainingDeletionRequest

KEY_SHARDS = 32
# A per-session deletion keeps the team month key, so it must also remove the seal that the month key opens.
KEY_MATERIAL_ATTRIBUTES = ("wrapped_key", "sealed_key", "key_nonce")
DynamoItem = dict[str, dict[str, str | bool | bytes]]


class DynamoResponse(TypedDict, total=False):
    Item: DynamoItem
    Items: list[DynamoItem]
    LastEvaluatedKey: DynamoItem


class DeletionWork(TypedDict, total=False):
    op: str
    team_id: int
    shard: int
    after: DynamoItem


class PrivacyDynamoClient(Protocol):
    def put_item(self, **kwargs: object) -> DynamoResponse: ...
    def get_item(self, **kwargs: object) -> DynamoResponse: ...
    def query(self, **kwargs: object) -> DynamoResponse: ...
    def transact_write_items(self, **kwargs: object) -> DynamoResponse: ...


class DeletionTarget(Protocol):
    # The request cursor stores each target's work under this key, so targets progress independently.
    cursor_key: str
    table_name: str

    def initialize(self, request: AITrainingDeletionRequest) -> list[DeletionWork]: ...
    def advance(self, work: DeletionWork) -> list[DeletionWork]: ...


def dynamo_client(region: str, endpoint: str) -> PrivacyDynamoClient:
    client = boto3.client(
        "dynamodb",
        region_name=region,
        endpoint_url=endpoint or None,
        config=Config(connect_timeout=5, read_timeout=5, retries={"max_attempts": 4, "mode": "standard"}),
    )
    return cast(PrivacyDynamoClient, client)


def item_key(pk: str, sk: str) -> DynamoItem:
    return {"pk": {"S": pk}, "sk": {"S": sk}}


def month_end(session_month: str) -> datetime:
    year, month = (int(part) for part in session_month.split("-"))
    return datetime(year + month // 12, month % 12 + 1, 1, tzinfo=UTC)


def identity_digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def session_key(team_id: int, session_id: str) -> DynamoItem:
    shard = int(identity_digest(session_id)[:8], 16) % KEY_SHARDS
    return item_key(f"team:{team_id}:shard:{shard}", f"session:{session_id}")


@frozen
class ReachableMonths:
    previous: str
    current: str
    following: str

    @property
    def months(self) -> list[str]:
        return [self.previous, self.current, self.following]


def reachable_months(now: datetime) -> ReachableMonths:
    current = f"{now:%Y-%m}"
    return ReachableMonths(
        previous=f"{datetime(now.year, now.month, 1, tzinfo=UTC) - timedelta(days=1):%Y-%m}",
        current=current,
        following=f"{month_end(current):%Y-%m}",
    )
