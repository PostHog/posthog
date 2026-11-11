from celery import shared_task

from posthog.scoping_audit import skip_team_scope_audit


@shared_task(ignore_result=True, soft_time_limit=120, time_limit=150)
@skip_team_scope_audit
def refresh_property_usage_map(team_id: int) -> None:
    """Rebuild the cached 30-day property usage map of one project."""
    # Deferred: posthog.taxonomy.property_usage imports this task to queue it.
    from posthog.taxonomy.property_usage import rebuild_property_usage_map_in_background  # noqa: PLC0415

    rebuild_property_usage_map_in_background(team_id)


@shared_task(ignore_result=True, soft_time_limit=120, time_limit=150)
@skip_team_scope_audit
def refresh_property_last_sent_map(team_id: int, property_type: str) -> None:
    """Rebuild the cached last-sent dates of one property type of one project."""
    # Deferred: posthog.taxonomy.property_last_sent imports this task to queue it.
    from posthog.taxonomy.property_last_sent import rebuild_property_last_sent_map_in_background  # noqa: PLC0415

    rebuild_property_last_sent_map_in_background(team_id, property_type)
