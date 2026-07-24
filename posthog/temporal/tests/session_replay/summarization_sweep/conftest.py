from posthog.models.team import Team
from posthog.models.user import User

from products.signals.backend.models import SignalSourceConfig


def enable_signal_source(team: Team, enabled: bool = True, created_by: User | None = None) -> None:
    team.organization.is_ai_data_processing_approved = True
    team.organization.save(update_fields=["is_ai_data_processing_approved"])
    SignalSourceConfig.objects.create(
        team=team,
        source_product=SignalSourceConfig.SourceProduct.SESSION_REPLAY,
        source_type=SignalSourceConfig.SourceType.SESSION_ANALYSIS_CLUSTER,
        enabled=enabled,
        created_by=created_by,
    )
