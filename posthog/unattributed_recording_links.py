from django.db.models import QuerySet

from posthog.dataclasses import frozen
from posthog.models.sharing_configuration import SharingConfiguration

# Stop counting early so large link histories do not delay the member review.
COUNT_LIMIT = 10_000
REVOKE_BATCH_SIZE = 1_000


@frozen
class UnattributedRecordingLinksCount:
    count: int
    count_is_capped: bool


def unattributed_recording_links(organization_id: str) -> QuerySet[SharingConfiguration]:
    # Recording links shared before publishers were recorded have no shared_by, and recordings have no
    # creator to fall back to, so a member review cannot tie these links to anyone.
    return SharingConfiguration.objects.filter(
        SharingConfiguration.tokens_active_q(),
        team__organization_id=organization_id,
        recording__isnull=False,
        shared_by__isnull=True,
    ).exclude(recording__deleted=True)


def count_unattributed_recording_links(organization_id: str) -> UnattributedRecordingLinksCount:
    count = unattributed_recording_links(organization_id)[: COUNT_LIMIT + 1].count()
    return UnattributedRecordingLinksCount(count=min(count, COUNT_LIMIT), count_is_capped=count > COUNT_LIMIT)


def revoke_unattributed_recording_links(organization_id: str) -> int:
    links = unattributed_recording_links(organization_id)
    revoked = 0
    while ids := list(links.values_list("pk", flat=True)[:REVOKE_BATCH_SIZE]):
        # A link shared again after the select gets a publisher. Re-check shared_by so that link stays public.
        revoked += links.filter(pk__in=ids).update(enabled=False)
    return revoked
