import posthoganalytics

from ...models.clustering_config import ClusteringConfig


def eligible_clustering_team_ids(team_ids: list[int] | None = None) -> set[int]:
    payload = posthoganalytics.get_feature_flag_payload(
        "llm-analytics-clustering-workflows", "internal_llma_team_discovery"
    )
    skipped = payload.get("skip_team_ids", []) if isinstance(payload, dict) else []
    if not isinstance(skipped, list) or any(not isinstance(value, int) for value in skipped):
        skipped = []
    configs = ClusteringConfig.objects.filter(
        enabled=True, team__organization__is_ai_data_processing_approved=True
    ).exclude(team_id__in=skipped)
    if team_ids is not None:
        configs = configs.filter(team_id__in=team_ids)
    return set(configs.values_list("team_id", flat=True))
