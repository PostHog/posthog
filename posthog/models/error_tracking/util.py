from posthog.kafka_client.client import ClickhouseProducer
from posthog.kafka_client.topics import KAFKA_PERSON_DISTINCT_ID
from posthog.models.person.sql import (
    INSERT_PERSON_DISTINCT_ID2,
)
from posthog.models.error_tracking import (
    ErrorTrackingIssueFingerprint,
)
from django.db import transaction


def update_error_tracking_issue_fingerprint(team_id: str, issue_id: str, fingerprint: list[str]) -> None:
    with transaction.atomic():
        issue_fingerprint = ErrorTrackingIssueFingerprint.objects.select_for_update().get(
            team_id=team_id, fingerprint=fingerprint
        )
        issue_fingerprint.issue_id = issue_id
        issue_fingerprint.version = (issue_fingerprint.version or 0) + 1
        issue_fingerprint.save(update_fields=["version", "issue_id"])

    create_error_tracking_issue_fingerprint(
        team_id=team_id,
        fingerprint=fingerprint,
        issue_id=issue_id,
        is_deleted=False,
        version=issue_fingerprint.version,
    )


def create_error_tracking_issue_fingerprint(
    team_id: int,
    fingerprint: str,
    issue_id: str,
    version=0,
    is_deleted: bool = False,
    sync: bool = False,
) -> None:
    p = ClickhouseProducer()
    p.produce(
        topic=KAFKA_PERSON_DISTINCT_ID,
        sql=INSERT_PERSON_DISTINCT_ID2,
        data={
            "team_id": team_id,
            "fingerprint": fingerprint,
            "issue_id": issue_id,
            "version": version,
            "is_deleted": int(is_deleted),
        },
        sync=sync,
    )
