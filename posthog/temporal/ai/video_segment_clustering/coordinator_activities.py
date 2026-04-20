"""Teams that have session analysis (session_problem) signals enabled via SignalSourceConfig."""

from temporalio import activity

from products.signals.backend.models import SignalSourceConfig


@activity.defn
async def list_teams_with_session_analysis_signals_activity() -> list[tuple[int, str]]:
    """Return (team_id, signal_source_config_id) for each enabled session replay session-analysis source."""
    enabled_configs: list[tuple[int, str]] = []
    async for config in SignalSourceConfig.objects.filter(
        source_product=SignalSourceConfig.SourceProduct.SESSION_REPLAY,
        source_type=SignalSourceConfig.SourceType.SESSION_ANALYSIS_CLUSTER,
        enabled=True,
    ).only("team_id", "id"):
        enabled_configs.append((config.team_id, str(config.id)))
    return enabled_configs
