from products.alerts.backend.models.alert import AlertConfiguration
from products.alerts_platform.backend.facade.contracts import SourceKind
from products.alerts_platform.backend.facade.creator_backfill_command import PlatformCreatorBackfillCommand


class Command(PlatformCreatorBackfillCommand):
    help = "Copy each insight alert's creator onto its alerts platform copy, where the copy has none."
    source_kind = SourceKind.INSIGHT
    source_model = AlertConfiguration
