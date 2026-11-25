import html
from urllib.parse import parse_qsl, urlencode

from django.conf import settings
from django.utils.text import Truncator

from posthog.helpers.email_utils import sanitize_display_name, sanitize_email_string
from posthog.models.organization import Organization

from ...facade.contracts import DigestRow
from ...logic.pending_review import PendingGroup, PendingKind
from .types import ProjectDigest

UTM_PARAMS = {"utm_source": "data_catalog_weekly_digest", "utm_medium": "email"}

SETTINGS_ANCHOR = "data-catalog-weekly-digest"

MAX_PROJECT_SECTIONS = 10

TEAM_NAME_FALLBACK = "Your project"

SAMPLE_NAME_MAX_CHARS = 60

ORGANIZATION_NAME_FALLBACK = "your organization"

PROPOSED_FILTER = {"filter": "proposed"}


def app_url(team_id: int, path: str) -> str:
    base, _, query = path.partition("?")
    params = {**dict(parse_qsl(query)), **UTM_PARAMS}
    return f"{settings.SITE_URL}/project/{team_id}{base}?{urlencode(params)}"


def catalog_path(kind: PendingKind) -> str:
    return f"/data-catalog?{urlencode({'tab': kind.value, **PROPOSED_FILTER})}"


def pending_rows(groups: list[PendingGroup]) -> list[DigestRow]:
    return [
        DigestRow(
            noun=group.noun,
            count=group.count,
            new_count=group.new_count,
            sample_names=group.sample_names,
            path=catalog_path(group.kind),
        )
        for group in groups
    ]


def settings_url() -> str:
    return f"{settings.SITE_URL}/settings/user-notifications?highlight={SETTINGS_ANCHOR}"


def build_project_section(project: ProjectDigest) -> dict:
    """One project block of the email: its rows, their links, and where the primary button goes."""
    busiest = max(project.rows, key=lambda row: row.count)
    return {
        "team_name": _defanged(sanitize_display_name(project.team_name, fallback=TEAM_NAME_FALLBACK)),
        "project_url": app_url(project.team_id, busiest.path),
        "total": project.total,
        "review_url": app_url(project.team_id, busiest.path),
        "rows": [_build_row(project.team_id, row) for row in project.rows],
    }


def _build_row(team_id: int, row: DigestRow) -> dict:
    sample_names = [_defanged(name) for name in row.sample_names if sanitize_display_name(name, fallback="")]
    return {
        "noun": row.noun,
        "count": row.count,
        "new_count": row.new_count,
        "sample_names": sample_names,
        "omitted_count": row.count - len(sample_names),
        "samples": _samples_text(sample_names, row.count - len(sample_names)),
        "review_url": app_url(team_id, row.path),
    }


def build_template_context(organization: Organization, projects: list[ProjectDigest]) -> dict:
    """Projects with new items first, then the busiest, capped so the email stays under the size mail clients clip at."""
    busiest_first = sorted(projects, key=lambda project: (project.new_total > 0, project.total), reverse=True)
    shown = busiest_first[:MAX_PROJECT_SECTIONS]
    return {
        "organization": organization,
        "organization_name": _defanged(sanitize_display_name(organization.name, fallback=ORGANIZATION_NAME_FALLBACK)),
        "total": sum(project.total for project in projects),
        "new_total": sum(project.new_total for project in projects),
        "project_sections": [build_project_section(project) for project in shown],
        "omitted_project_count": len(busiest_first) - len(shown),
        "settings_url": settings_url(),
    }


def _samples_text(names: list[str], omitted_count: int) -> str:
    parts = [", ".join(Truncator(name).chars(SAMPLE_NAME_MAX_CHARS) for name in names)] if names else []
    if omitted_count:
        parts.append(f"and {omitted_count} more")
    return " ".join(parts)


def _defanged(text: str) -> str:
    """Breaks domain-shaped text so mail clients cannot auto-link it, and leaves the HTML escaping to the template."""
    return html.unescape(sanitize_email_string(text))


def build_subject(new_total: int, total: int) -> str:
    count = new_total or total
    item_word = "item" if count == 1 else "items"
    new_word = "new " if new_total else ""
    return f"{count} {new_word}{item_word} to review in your data catalog"
