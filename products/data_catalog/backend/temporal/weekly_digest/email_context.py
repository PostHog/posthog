from urllib.parse import urlencode

from django.conf import settings

from ...logic.pending_review import PendingKind, TeamPendingReview

UTM_PARAMS = {"utm_source": "data_catalog_weekly_digest", "utm_medium": "email"}

SETTINGS_ANCHOR = "data-catalog-weekly-digest"


def catalog_url(team_id: int, kind: PendingKind | None = None) -> str:
    params = {"tab": kind.value, **UTM_PARAMS} if kind else dict(UTM_PARAMS)
    return f"{settings.SITE_URL}/project/{team_id}/data-catalog?{urlencode(params)}"


def settings_url() -> str:
    return f"{settings.SITE_URL}/settings/user-notifications?highlight={SETTINGS_ANCHOR}"


def build_project_section(review: TeamPendingReview) -> dict:
    """One project block of the email: its queues, their links, and where the primary button goes."""
    busiest = max(review.groups, key=lambda group: group.count)
    return {
        "team_name": review.team_name,
        "project_url": catalog_url(review.team_id),
        "total": review.total,
        "review_url": catalog_url(review.team_id, busiest.kind),
        "create_metric_url": catalog_url(review.team_id, PendingKind.METRICS),
        "rows": [
            {
                "noun": group.noun,
                "count": group.count,
                "sample_names": group.sample_names,
                "omitted_count": group.count - len(group.sample_names),
                "review_url": catalog_url(review.team_id, group.kind),
            }
            for group in review.groups
        ],
    }


def build_subject(total: int) -> str:
    item_word = "item" if total == 1 else "items"
    return f"{total} {item_word} awaiting review in your data catalog"
