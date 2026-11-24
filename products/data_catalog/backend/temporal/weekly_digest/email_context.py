from urllib.parse import parse_qsl, urlencode

from django.conf import settings

from posthog.helpers.email_utils import sanitize_display_name
from posthog.models.organization import Organization

from ...facade.contracts import DigestRow
from ...logic.pending_review import PendingKind, TeamPendingReview
from .types import ProjectDigest

UTM_PARAMS = {"utm_source": "data_catalog_weekly_digest", "utm_medium": "email"}

SETTINGS_ANCHOR = "data-catalog-weekly-digest"

MAX_PROJECT_SECTIONS = 10

TEAM_NAME_FALLBACK = "Your project"

ORGANIZATION_NAME_FALLBACK = "your organization"

PROPOSED_FILTER = {"filter": "proposed"}


def app_url(team_id: int, path: str) -> str:
    base, _, query = path.partition("?")
    params = {**dict(parse_qsl(query)), **UTM_PARAMS}
    return f"{settings.SITE_URL}/project/{team_id}{base}?{urlencode(params)}"


def catalog_path(kind: PendingKind | None = None) -> str:
    if kind is None:
        return "/data-catalog"
    return f"/data-catalog?{urlencode({'tab': kind.value, **PROPOSED_FILTER})}"


def catalog_url(team_id: int, kind: PendingKind | None = None) -> str:
    return app_url(team_id, catalog_path(kind))


def pending_rows(review: TeamPendingReview) -> list[DigestRow]:
    return [
        DigestRow(
            noun=group.noun,
            count=group.count,
            new_count=group.new_count,
            sample_names=group.sample_names,
            path=catalog_path(group.kind),
        )
        for group in review.groups
    ]


def settings_url() -> str:
    return f"{settings.SITE_URL}/settings/user-notifications?highlight={SETTINGS_ANCHOR}"


def build_project_section(project: ProjectDigest) -> dict:
    """One project block of the email: its rows, their links, and where the primary button goes."""
    busiest = max(project.rows, key=lambda row: row.count)
    return {
        "team_name": sanitize_display_name(project.team_name, fallback=TEAM_NAME_FALLBACK),
        "project_url": catalog_url(project.team_id),
        "total": project.total,
        "review_url": app_url(project.team_id, busiest.path),
        "rows": [_build_row(project.team_id, row) for row in project.rows],
    }


def _build_row(team_id: int, row: DigestRow) -> dict:
    sample_names = [name for name in row.sample_names if sanitize_display_name(name, fallback="")]
    return {
        "noun": row.noun,
        "count": row.count,
        "new_count": row.new_count,
        "sample_names": sample_names,
        "omitted_count": row.count - len(sample_names),
        "review_url": app_url(team_id, row.path),
    }


def build_template_context(organization: Organization, projects: list[ProjectDigest]) -> dict:
    """The busiest projects first, capped so the email stays under the size mail clients clip at."""
    busiest_first = sorted(projects, key=lambda project: project.total, reverse=True)
    shown = busiest_first[:MAX_PROJECT_SECTIONS]
    return {
        "organization": organization,
        "organization_name": sanitize_display_name(organization.name, fallback=ORGANIZATION_NAME_FALLBACK),
        "total": sum(project.total for project in projects),
        "new_total": sum(project.new_total for project in projects),
        "project_sections": [build_project_section(project) for project in shown],
        "omitted_project_count": len(busiest_first) - len(shown),
        "settings_url": settings_url(),
    }


def build_subject(new_total: int, total: int) -> str:
    count = new_total or total
    item_word = "item" if count == 1 else "items"
    new_word = "new " if new_total else ""
    return f"{count} {new_word}{item_word} to review in your data catalog"
