from posthog.models.team import Team

from products.signals.backend.models import SignalSourceConfig


def enable_signal_source(team: Team, enabled: bool = True) -> None:
    SignalSourceConfig.objects.create(
        team=team,
        source_product=SignalSourceConfig.SourceProduct.SESSION_REPLAY,
        source_type=SignalSourceConfig.SourceType.SESSION_ANALYSIS_CLUSTER,
        enabled=enabled,
    )
