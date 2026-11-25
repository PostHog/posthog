def consented_team_ids(team_ids: list[int]) -> set[int]:
    """Of the given teams, the ones whose organization approved third-party AI data processing.

    The flag is nullable, and every reader treats an unset flag as not approved. A team that
    no longer exists is absent from the result, so a caller fails closed on both.
    """
    from posthog.models import Team  # noqa: PLC0415 - keeps Django models off the workflow import path

    return set(
        Team.objects.filter(id__in=team_ids, organization__is_ai_data_processing_approved=True).values_list(
            "id", flat=True
        )
    )
