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
from botocore.exceptions import ClientError

from posthog.ai_training_privacy_reader import KEY_READ_LEASE_SECONDS
from posthog.models.ai_training import AITrainingPrivacyRequest

logger = structlog.get_logger(__name__)

KEY_SHARDS = 32
DynamoItem = dict[str, dict[str, str | bool | bytes]]


class DynamoResponse(TypedDict, total=False):
    Item: DynamoItem
    Items: list[DynamoItem]
    LastEvaluatedKey: DynamoItem


class DeletionWork(TypedDict, total=False):
    op: str
    organization_id: str
    team_id: int
    session_id: str
    digest: str
    shard: int
    withdrawn_at: int
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
        return cls(cast(PrivacyDynamoClient, client), settings.AI_RESEARCH_REPLAY_PRIVACY_TABLE)

    def block(self, team_id: int, distinct_id: str | None = None) -> None:
        key = item_key(
            f"team:{team_id}", f"distinct:{identity_digest(distinct_id)}" if distinct_id is not None else "deleted"
        )
        self.client.put_item(TableName=self.table_name, Item={**key, "deleted": {"BOOL": True}})

    def update_consent(self, request: AITrainingPrivacyRequest) -> None:
        try:
            self.client.put_item(
                TableName=self.table_name,
                Item={
                    **item_key(f"organization:{request.organization_id}", "consent"),
                    "allowed": {"BOOL": request.allowed is True},
                    "granted_at": {"N": str(request.granted_at_ms)},
                    "revision": {"N": str(request.revision)},
                    "changed_at": {"N": str(request.changed_at_ms)},
                },
                ConditionExpression="attribute_not_exists(revision) OR revision < :revision",
                ExpressionAttributeValues={":revision": {"N": str(request.revision)}},
            )
        except ClientError as error:
            if error.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise

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

    def initialize(self, request: AITrainingPrivacyRequest) -> list[DeletionWork]:
        if request.kind == "consent":
            self.update_consent(request)
            return (
                []
                if request.allowed
                else [
                    {
                        "op": "organization",
                        "organization_id": str(request.organization_id),
                        "withdrawn_at": request.changed_at_ms,
                    }
                ]
            )
        if request.team_id is None:
            raise ValueError("AI training deletion request has no team")
        team_id = request.team_id
        if request.kind == "team":
            self.block(team_id)
            return [{"op": "team", "team_id": team_id, "shard": -1}]
        if request.kind == "session":
            self.shred([session_key(team_id, value) for value in request.identifiers])
            return [{"op": "associations", "team_id": team_id, "session_id": value} for value in request.identifiers]
        if request.kind == "distinct":
            for offset in range(0, len(request.identifiers), 100):
                self.client.transact_write_items(
                    TransactItems=[
                        {
                            "Put": {
                                "TableName": self.table_name,
                                "Item": {
                                    **item_key(f"team:{team_id}", f"distinct:{identity_digest(value)}"),
                                    "deleted": {"BOOL": True},
                                },
                            }
                        }
                        for value in request.identifiers[offset : offset + 100]
                    ]
                )
            return [
                {"op": "distinct", "team_id": team_id, "digest": identity_digest(value), "shard": 0}
                for value in request.identifiers
            ]
        raise ValueError("Unknown AI training deletion request")

    def advance(self, work: DeletionWork) -> list[DeletionWork]:
        operation = work["op"]
        if operation == "organization":
            response = self.page(f"organization:{work['organization_id']}", "team:", work.get("after"))
            children: list[DeletionWork] = [
                {
                    "op": "team",
                    "team_id": int(str(row["team_id"]["N"])),
                    "shard": -1,
                    "withdrawn_at": work["withdrawn_at"],
                }
                for row in response.get("Items", [])
            ]
            continuation: list[DeletionWork] = (
                [{**work, "after": response["LastEvaluatedKey"]}] if response.get("LastEvaluatedKey") else []
            )
            return children + continuation
        team_id = int(work["team_id"])
        if operation == "associations":
            session_id = str(work["session_id"])
            response = self.page(f"team:{team_id}:session:{session_id}", "distinct:", work.get("after"))
            deletions: list[DynamoItem] = []
            for row in response.get("Items", []):
                deletions.append({"pk": row["pk"], "sk": row["sk"]})
                forward_pk = row.get("forward_pk", {}).get("S")
                if isinstance(forward_pk, str):
                    deletions.append(item_key(forward_pk, f"session:{session_id}"))
            if deletions:
                self.client.transact_write_items(
                    TransactItems=[{"Delete": {"TableName": self.table_name, "Key": key}} for key in deletions]
                )
            return [{**work, "after": response["LastEvaluatedKey"]}] if response.get("LastEvaluatedKey") else []
        shard = int(work["shard"])
        if operation == "team":
            pk = f"team:{team_id}" if shard == -1 else f"team:{team_id}:shard:{shard}"
            prefix = "image:" if shard == -1 else "session:"
        elif operation == "distinct":
            pk, prefix = f"team:{team_id}:distinct:{work['digest']}:shard:{shard}", "session:"
        else:
            raise ValueError("Unknown AI training deletion operation")
        response = self.page(pk, prefix, work.get("after"))
        rows = response.get("Items", [])
        withdrawn_at = work.get("withdrawn_at")
        if withdrawn_at is not None:
            rows = [row for row in rows if int(str(row.get("granted_at", {}).get("N", "0"))) <= int(withdrawn_at)]
        sessions = [str(row["sk"]["S"]).removeprefix("session:") for row in rows] if prefix == "session:" else []
        self.shred([session_key(team_id, session_id) for session_id in sessions] if operation == "distinct" else rows)
        association_work: list[DeletionWork] = [
            {"op": "associations", "team_id": team_id, "session_id": session_id} for session_id in sessions
        ]
        if response.get("LastEvaluatedKey"):
            return [*association_work, {**work, "after": response["LastEvaluatedKey"]}]
        if shard + 1 < KEY_SHARDS:
            next_work: DeletionWork = {**work, "shard": shard + 1}
            next_work.pop("after", None)
            return [*association_work, next_work]
        return association_work

    def apply(self, request: AITrainingPrivacyRequest, deadline: float) -> bool:
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
        if not (request.kind == "consent" and request.allowed):
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
                    AITrainingPrivacyRequest.objects.unscoped()
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
                logger.exception("ai_training_privacy_request_failed", request_id=str(request.pk), kind=request.kind)
                request.leased_until = timezone.now() + timedelta(minutes=5)
            else:
                request.leased_until = max(
                    timezone.now(),
                    datetime.fromtimestamp(request.cursor.get("complete_after", 0), tz=timezone.get_current_timezone()),
                )
            request.save(update_fields=["leased_until"])
        return completed
