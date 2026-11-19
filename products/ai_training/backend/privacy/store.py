import re
import time
from collections.abc import Sequence
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

import structlog

from products.ai_training.backend.config import key_table_name, v4_key_table_name
from products.ai_training.backend.models import AITrainingDeletionRequest
from products.ai_training.backend.privacy.keys import (
    KEY_MATERIAL_ATTRIBUTES,
    KEY_SHARDS,
    DeletionTarget,
    DeletionWork,
    DynamoItem,
    DynamoResponse,
    PrivacyDynamoClient,
    dynamo_client,
    item_key,
    month_end,
    reachable_months,
    session_key,
)
from products.ai_training.backend.privacy.v4 import V4KeyTarget

logger = structlog.get_logger(__name__)

# Equals ML_SESSION_MAX_AGE_DAYS in nodejs/src/ingestion/pipelines/sessionreplay/ml-mirror/session-identifier-format.ts: ingestion drops sessions that started earlier than that, so no key for a month can appear after the month end plus this period.
MONTH_DELETE_GRACE_DAYS = 14
# A batch admitted just inside the grace period still commits within its 45 s budget, so deletion stays behind that too.
MONTH_DELETE_IN_FLIGHT_MARGIN = timedelta(hours=1)


class V3KeyTarget:
    cursor_key = "work"

    def __init__(self, client: PrivacyDynamoClient, table_name: str) -> None:
        self.client = client
        self.table_name = table_name

    @classmethod
    def from_settings(cls) -> "V3KeyTarget":
        client = dynamo_client(settings.AI_RESEARCH_REPLAY_AWS_REGION, settings.AI_RESEARCH_REPLAY_DYNAMODB_ENDPOINT)
        return cls(client, key_table_name())

    def delete_month(self, session_month: str) -> int:
        if re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", session_month) is None:
            raise ValueError("Session month must use YYYY-MM")
        try:
            deletable_from = (
                month_end(session_month) + timedelta(days=MONTH_DELETE_GRACE_DAYS) + MONTH_DELETE_IN_FLIGHT_MARGIN
            )
        except ValueError as error:
            raise ValueError("Session month must use YYYY-MM") from error
        if timezone.now() < deletable_from:
            raise ValueError(
                f"Session month {session_month} can be deleted from {deletable_from:%Y-%m-%d %H:%M} UTC, "
                f"{MONTH_DELETE_GRACE_DAYS} days and one hour after the month ends"
            )
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
                            "UpdateExpression": "SET deleted = :deleted REMOVE " + ", ".join(KEY_MATERIAL_ATTRIBUTES),
                            "ExpressionAttributeValues": {":deleted": {"BOOL": True}},
                        },
                    }
                    for key in values[offset : offset + 100]
                ]
            )

    # A sweep reaches only an image key that already exists, so a team that keeps sending would open a month the sweep never saw. Ingestion admits a session up to ML_SESSION_MAX_AGE_DAYS old, which is inside one month, so these three are every month a later session can still open. An update creates the row, so each one closes whether or not it holds a key.
    def shred_reachable_months(self, team_id: int) -> None:
        self.shred([item_key(f"team:{team_id}", f"image:{month}") for month in reachable_months(timezone.now()).months])

    def initialize(self, request: AITrainingDeletionRequest) -> list[DeletionWork]:
        if request.team_id is None:
            raise ValueError("AI training deletion request has no team")
        team_id = request.team_id
        if request.kind == "team":
            self.shred_reachable_months(team_id)
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


class AITrainingPrivacyStore:
    def __init__(self, targets: Sequence[DeletionTarget]) -> None:
        self.targets = list(targets)

    @classmethod
    def from_settings(cls) -> "AITrainingPrivacyStore":
        targets: list[DeletionTarget] = []
        if key_table_name():
            targets.append(V3KeyTarget.from_settings())
        if v4_key_table_name():
            targets.append(V4KeyTarget.from_settings())
        return cls(targets)

    def apply(self, request: AITrainingDeletionRequest, deadline: float) -> bool:
        for target in self.targets:
            work = request.cursor.get(target.cursor_key)
            if work is None:
                # Initialization writes with retries, so a target that starts after the deadline can overrun the task time limit.
                if time.monotonic() >= deadline:
                    return False
                work = target.initialize(request)
                self.save_cursor(request, **{target.cursor_key: work})
            while work:
                if time.monotonic() >= deadline:
                    return False
                work = target.advance(work[0]) + work[1:]
                self.save_cursor(request, **{target.cursor_key: work})
        # A key that a batch stores after the sweep passes its shard is sealed under a month key this deletion already tombstoned, so a second sweep finds nothing that is readable. The sweep removes rows to save cost. See products/ai_training/docs/replay-data.md.
        request.completed_at = timezone.now()
        request.identifiers = []
        request.save(update_fields=["completed_at", "identifiers"])
        return True

    def save_cursor(self, request: AITrainingDeletionRequest, **fields: object) -> None:
        request.cursor = {**request.cursor, **fields}
        request.save(update_fields=["cursor"])

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
                request.leased_until = timezone.now()
            request.save(update_fields=["leased_until"])
        return completed
