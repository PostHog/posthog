from products.alerts.backend.models.alert import AlertConfiguration
from products.alerts_platform.backend.facade.contracts import SourceKind
from products.alerts_platform.backend.facade.created_at_backfill_command import PlatformCreatedAtBackfillCommand


class Command(PlatformCreatedAtBackfillCommand):
    help = (
        "Copy each insight alert's created_at onto its alerts platform copy, where the two differ. "
        "Writes nothing without --apply."
    )
    source_kind = SourceKind.INSIGHT
    source_model = AlertConfiguration
