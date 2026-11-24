from urllib.parse import urlencode

from django.conf import settings

from posthog.helpers.email_utils import sanitize_display_name
from posthog.models.organization import Organization

from ...logic.pending_review import PendingGroup, PendingKind, TeamPendingReview

UTM_PARAMS = {"utm_source": "data_catalog_weekly_digest", "utm_medium": "email"}

SETTINGS_ANCHOR = "data-catalog-weekly-digest"

MAX_PROJECT_SECTIONS = 10

TEAM_NAME_FALLBACK = "Your project"

ORGANIZATION_NAME_FALLBACK = "your organization"

PROPOSED_FILTER = {"filter": "proposed"}


def catalog_url(team_id: int, kind: PendingKind | None = None) -> str:
    params = {"tab": kind.value, **PROPOSED_FILTER, **UTM_PARAMS} if kind else dict(UTM_PARAMS)
    return f"{settings.SITE_URL}/project/{team_id}/data-catalog?{urlencode(params)}"


def settings_url() -> str:
    return f"{settings.SITE_URL}/settings/user-notifications?highlight={SETTINGS_ANCHOR}"


def build_project_section(review: TeamPendingReview) -> dict:
    """One project block of the email: its queues, their links, and where the primary button goes."""
    busiest = max(review.groups, key=lambda group: group.count)
    return {
        "team_name": sanitize_display_name(review.team_name, fallback=TEAM_NAME_FALLBACK),
        "project_url": catalog_url(review.team_id),
        "total": review.total,
        "review_url": catalog_url(review.team_id, busiest.kind),
        "rows": [_build_row(review.team_id, group) for group in review.groups],
    }


def _build_row(team_id: int, group: PendingGroup) -> dict:
    sample_names = [name for name in group.sample_names if sanitize_display_name(name, fallback="")]
    return {
        "noun": group.noun,
        "count": group.count,
        "new_count": group.new_count,
        "sample_names": sample_names,
        "omitted_count": group.count - len(sample_names),
        "review_url": catalog_url(team_id, group.kind),
    }


def build_template_context(organization: Organization, reviews: list[TeamPendingReview]) -> dict:
    """The busiest projects first, capped so the email stays under the size mail clients clip at."""
    busiest_first = sorted(reviews, key=lambda review: review.total, reverse=True)
    shown = busiest_first[:MAX_PROJECT_SECTIONS]
    return {
        "organization": organization,
        "organization_name": sanitize_display_name(organization.name, fallback=ORGANIZATION_NAME_FALLBACK),
        "total": sum(review.total for review in reviews),
        "new_total": sum(group.new_count for review in reviews for group in review.groups),
        "project_sections": [build_project_section(review) for review in shown],
        "omitted_project_count": len(busiest_first) - len(shown),
        "settings_url": settings_url(),
    }


def build_subject(new_total: int, total: int) -> str:
    count = new_total or total
    item_word = "item" if count == 1 else "items"
    new_word = "new " if new_total else ""
    return f"{count} {new_word}{item_word} to review in your data catalog"
