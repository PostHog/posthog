from __future__ import annotations

from django.utils import timezone

from posthog.models.scoping.manager import resolve_effective_team_id

from products.aeo.backend.models import AEOTeamConfig


def enabled_team_ids() -> list[int]:
    return list(
        AEOTeamConfig.objects.unscoped()
        .filter(enabled_at__isnull=False)
        .order_by("team_id")
        .values_list("team_id", flat=True)
    )


def is_enabled(team_id: int) -> bool:
    return AEOTeamConfig.objects.for_team(team_id).filter(enabled_at__isnull=False).exists()


def enable(team_id: int, *, user_id: int | None) -> None:
    canonical = resolve_effective_team_id(team_id)
    now = timezone.now()
    configs = AEOTeamConfig.objects.for_team(canonical, canonical=True)
    _, created = configs.get_or_create(team_id=canonical, defaults={"enabled_at": now, "enabled_by_id": user_id})
    if not created:
        configs.filter(enabled_at__isnull=True).update(enabled_at=now, enabled_by_id=user_id)
