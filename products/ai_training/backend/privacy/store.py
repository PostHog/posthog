import re
import time
import hashlib
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Protocol, TypedDict, cast

from django.conf import settings
from django.db import transaction
from django.utils import timezone

import boto3
import structlog
from botocore.config import Config

from products.ai_training.backend.config import key_table_name
from products.ai_training.backend.models import AITrainingDeletionRequest
from products.ai_training.backend.privacy.reader import KEY_READ_LEASE_SECONDS

logger = structlog.get_logger(__name__)

KEY_SHARDS = 32
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


def item_key(pk: str, sk: str) -> DynamoItem:
    return {"pk": {"S": pk}, "sk": {"S": sk}}


def identity_digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def session_key(team_id: int, session_id: str) -> DynamoItem:
    shard = int(identity_digest(session_id)[:8], 16) % KEY_SHARDS
    return item_key(f"team:{team_id}:shard:{shard}", f"session:{session_id}")


class AITrainingPrivacyStore:
    def __init__(self, client: PrivacyDynamoClient, table_name: str) -> None:
        self.client = client
        self.table_name = table_name

    @classmethod
    def from_settings(cls) -> "AITrainingPrivacyStore":
        client = boto3.client(
            "dynamodb",
            region_name=settings.AI_RESEARCH_REPLAY_AWS_REGION,
            endpoint_url=settings.AI_RESEARCH_REPLAY_DYNAMODB_ENDPOINT or None,
            config=Config(connect_timeout=5, read_timeout=5, retries={"max_attempts": 4, "mode": "standard"}),
        )
        return cls(cast(PrivacyDynamoClient, client), key_table_name())

    def block(self, team_id: int) -> None:
        self.client.put_item(
            TableName=self.table_name, Item={**item_key(f"team:{team_id}", "deleted"), "deleted": {"BOOL": True}}
        )

    def delete_month(self, session_month: str) -> int:
        if re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", session_month) is None:
            raise ValueError("Session month must use YYYY-MM")
        count = 0
        for shard in range(KEY_SHARDS):
            cursor = None
            while True:
                response = self.page(f"month:{session_month}:shard:{shard}", "key:", cursor)
                rows = response.get("Items", [])
                self.shred([item_key(str(row["key_pk"]["S"]), str(row["key_sk"]["S"])) for row in rows])
                count += len(rows)
                cursor = response.get("LastEvaluatedKey")
                if not cursor:
                    break
        return count

    def page(self, pk: str, prefix: str, cursor: DynamoItem | None = None) -> DynamoResponse:
        return self.client.query(
            TableName=self.table_name,
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues={":pk": {"S": pk}, ":prefix": {"S": prefix}},
            ConsistentRead=True,
            Limit=50,
            **({"ExclusiveStartKey": cursor} if cursor else {}),
        )

    def shred(self, keys: Sequence[DynamoItem]) -> None:
        unique = {str(key["pk"]["S"]) + "\0" + str(key["sk"]["S"]): key for key in keys}
        values = list(unique.values())
        for offset in range(0, len(values), 100):
            self.client.transact_write_items(
                TransactItems=[
                    {
                        "Update": {
                            "TableName": self.table_name,
                            "Key": {"pk": key["pk"], "sk": key["sk"]},
                            "UpdateExpression": "SET deleted = :deleted REMOVE wrapped_key",
                            "ExpressionAttributeValues": {":deleted": {"BOOL": True}},
                        },
                    }
                    for key in values[offset : offset + 100]
                ]
            )

    def initialize(self, request: AITrainingDeletionRequest) -> list[DeletionWork]:
        if request.team_id is None:
            raise ValueError("AI training deletion request has no team")
        team_id = request.team_id
        if request.kind == "team":
            self.block(team_id)
            return [{"op": "team", "team_id": team_id, "shard": -1}]
        if request.kind == "session":
            self.shred([session_key(team_id, value) for value in request.identifiers])
            return []
        raise ValueError("Unknown AI training deletion request")

    def advance(self, work: DeletionWork) -> list[DeletionWork]:
        if work["op"] != "team":
            raise ValueError("Unknown AI training deletion operation")
        team_id = int(work["team_id"])
        shard = int(work["shard"])
        pk = f"team:{team_id}" if shard == -1 else f"team:{team_id}:shard:{shard}"
        prefix = "image:" if shard == -1 else "session:"
        response = self.page(pk, prefix, work.get("after"))
        self.shred(response.get("Items", []))
        if response.get("LastEvaluatedKey"):
            return [{**work, "after": response["LastEvaluatedKey"]}]
        if shard + 1 < KEY_SHARDS:
            next_work: DeletionWork = {**work, "shard": shard + 1}
            next_work.pop("after", None)
            return [next_work]
        return []

    def apply(self, request: AITrainingDeletionRequest, deadline: float) -> bool:
        work = request.cursor.get("work")
        if work is None:
            work = self.initialize(request)
            request.cursor = {"work": work}
            request.save(update_fields=["cursor"])
        while work:
            if time.monotonic() >= deadline:
                return False
            work = self.advance(work[0]) + work[1:]
            request.cursor = {"work": work}
            request.save(update_fields=["cursor"])
        now = timezone.now()
        complete_after = request.cursor.get("complete_after")
        if complete_after is None:
            request.cursor = {"work": [], "complete_after": now.timestamp() + KEY_READ_LEASE_SECONDS}
            request.save(update_fields=["cursor"])
            return False
        if now.timestamp() < complete_after:
            return False
        request.completed_at = now
        request.identifiers = []
        request.save(update_fields=["completed_at", "identifiers"])
        return True

    def drain(self, limit: int = 100, budget_seconds: int = 240) -> int:
        deadline = time.monotonic() + budget_seconds
        completed = 0
        for _ in range(limit):
            if time.monotonic() >= deadline:
                break
            with transaction.atomic():
                request = (
                    AITrainingDeletionRequest.objects.unscoped()
                    .select_for_update(skip_locked=True)
                    .filter(completed_at__isnull=True, leased_until__lte=timezone.now())
                    .order_by("created_at")
                    .first()
                )
                if request is None:
                    break
                request.leased_until = timezone.now() + timedelta(seconds=300)
                request.save(update_fields=["leased_until"])
            try:
                completed += int(self.apply(request, deadline))
            except Exception:
                logger.exception("ai_training_deletion_request_failed", request_id=str(request.pk), kind=request.kind)
                request.leased_until = timezone.now() + timedelta(minutes=5)
            else:
                request.leased_until = max(
                    timezone.now(),
                    datetime.fromtimestamp(request.cursor.get("complete_after", 0), tz=timezone.get_current_timezone()),
                )
            request.save(update_fields=["leased_until"])
        return completed
