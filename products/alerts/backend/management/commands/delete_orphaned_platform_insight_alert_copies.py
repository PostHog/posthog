from collections.abc import Collection
from uuid import UUID

from products.alerts.backend.models.alert import AlertConfiguration
from products.alerts_platform.backend.facade.contracts import SourceKind
from products.alerts_platform.backend.facade.orphan_cleanup_command import PlatformOrphanCleanupCommand


class Command(PlatformOrphanCleanupCommand):
    help = "Delete the alerts platform's shadow copies of insight alerts that no longer exist."
    source_kind = SourceKind.INSIGHT

    def existing_source_ids(self, ids: Collection[UUID]) -> Collection[UUID]:
        # nosemgrep: idor-lookup-without-team
        return set(AlertConfiguration.objects.filter(id__in=ids).values_list("id", flat=True))
