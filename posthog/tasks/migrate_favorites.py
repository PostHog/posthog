from django.utils.timezone import now

from celery import shared_task

from posthog.models import Insight, InsightFavorite, Team, User
from posthog.models.organization import OrganizationMembership


@shared_task(ignore_result=True)
def migrate_user_favorites(user_id: int) -> None:
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return

    if user.favorites_migrated_at:
        return

    org_ids = OrganizationMembership.objects.filter(user=user).values_list("organization_id", flat=True)
    team_ids = Team.objects.filter(organization_id__in=org_ids).values_list("id", flat=True)

    global_favorites = Insight.objects_including_soft_deleted.filter(
        team_id__in=team_ids,
        favorited=True,
        deleted=False,
    ).values_list("id", "team_id")

    new_favorites = [
        InsightFavorite(user=user, insight_id=insight_id, team_id=team_id) for insight_id, team_id in global_favorites
    ]
    InsightFavorite.objects.bulk_create(new_favorites, ignore_conflicts=True)

    user.favorites_migrated_at = now()
    user.save(update_fields=["favorites_migrated_at"])
