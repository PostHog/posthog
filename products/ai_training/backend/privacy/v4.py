from collections.abc import Sequence
from datetime import UTC, datetime

from django.conf import settings
from django.utils import timezone

from products.ai_training.backend.config import v4_key_table_name
from products.ai_training.backend.models import AITrainingDeletionRequest
from products.ai_training.backend.privacy.keys import (
    KEY_MATERIAL_ATTRIBUTES,
    KEY_SHARDS,
    DeletionWork,
    DynamoItem,
    DynamoResponse,
    PrivacyDynamoClient,
    dynamo_client,
    item_key,
    reachable_months,
    session_key,
)

# Equals the expiry rule of the v4 recorder: a row lives until the start of the fifth month after its key month.
KEY_RETENTION_MONTHS = 5


def key_expiry(key_month: str) -> int:
    year, month = (int(part) for part in key_month.split("-"))
    index = year * 12 + month - 1 + KEY_RETENTION_MONTHS
    return int(datetime(index // 12, index % 12 + 1, 1, tzinfo=UTC).timestamp())


class V4KeyTarget:
    cursor_key = "v4_work"

    def __init__(self, client: PrivacyDynamoClient, table_name: str) -> None:
        self.client = client
        self.table_name = table_name

    @classmethod
    def from_settings(cls) -> "V4KeyTarget":
        client = dynamo_client(settings.AI_RESEARCH_V4_AWS_REGION, settings.AI_RESEARCH_V4_DYNAMODB_ENDPOINT)
        return cls(client, v4_key_table_name())

    def page(self, pk: str, prefix: str, cursor: DynamoItem | None = None) -> DynamoResponse:
        return self.client.query(
            TableName=self.table_name,
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues={":pk": {"S": pk}, ":prefix": {"S": prefix}},
            ProjectionExpression="pk, sk",
            ConsistentRead=True,
            Limit=50,
            **({"ExclusiveStartKey": cursor} if cursor else {}),
        )

    # An update creates a row that does not exist yet, and writers never overwrite a row, so the tombstone needs an expiry or it stays forever. if_not_exists keeps the expiry of a row the recorder wrote.
    def tombstone(self, rows: Sequence[tuple[DynamoItem, int]]) -> None:
        unique = {str(key["pk"]["S"]) + "\0" + str(key["sk"]["S"]): (key, expiry) for key, expiry in rows}
        values = list(unique.values())
        for offset in range(0, len(values), 100):
            self.client.transact_write_items(
                TransactItems=[
                    {
                        "Update": {
                            "TableName": self.table_name,
                            "Key": {"pk": key["pk"], "sk": key["sk"]},
                            "UpdateExpression": "SET deleted = :true, expires_at = if_not_exists(expires_at, :expiry) REMOVE "
                            + ", ".join(KEY_MATERIAL_ATTRIBUTES),
                            "ExpressionAttributeValues": {":true": {"BOOL": True}, ":expiry": {"N": str(expiry)}},
                        },
                    }
                    for key, expiry in values[offset : offset + 100]
                ]
            )

    def month_row(self, team_id: int, key_month: str) -> tuple[DynamoItem, int]:
        return item_key(f"team:{team_id}", f"month:{key_month}"), key_expiry(key_month)

    def session_expiry(self) -> int:
        return key_expiry(f"{timezone.now():%Y-%m}")

    def initialize(self, request: AITrainingDeletionRequest) -> list[DeletionWork]:
        if request.team_id is None:
            raise ValueError("AI training deletion request has no team")
        team_id = request.team_id
        if request.kind == "team":
            # A session can still open these months after the sweep passes, and a tombstone stops the recorder from writing a key there.
            self.tombstone([self.month_row(team_id, month) for month in reachable_months(timezone.now()).months])
            return [{"op": "team", "team_id": team_id, "shard": -1}]
        if request.kind == "session":
            expiry = self.session_expiry()
            self.tombstone([(session_key(team_id, value), expiry) for value in request.identifiers])
            return []
        raise ValueError("Unknown AI training deletion request")

    def advance(self, work: DeletionWork) -> list[DeletionWork]:
        if work["op"] != "team":
            raise ValueError("Unknown AI training deletion operation")
        team_id = int(work["team_id"])
        shard = int(work["shard"])
        if shard == -1:
            response = self.page(f"team:{team_id}", "month:", work.get("after"))
            self.tombstone(
                [
                    self.month_row(team_id, str(row["sk"]["S"]).removeprefix("month:"))
                    for row in response.get("Items", [])
                ]
            )
        else:
            response = self.page(f"team:{team_id}:shard:{shard}", "session:", work.get("after"))
            expiry = self.session_expiry()
            self.tombstone(
                [(item_key(str(row["pk"]["S"]), str(row["sk"]["S"])), expiry) for row in response.get("Items", [])]
            )
        if response.get("LastEvaluatedKey"):
            return [{**work, "after": response["LastEvaluatedKey"]}]
        if shard + 1 < KEY_SHARDS:
            next_work: DeletionWork = {**work, "shard": shard + 1}
            next_work.pop("after", None)
            return [next_work]
        return []
