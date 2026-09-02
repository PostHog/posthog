"""The on-disk shape of a wiki page: frontmatter, then one heading, then the body.

Every writer goes through here, so a page the import writes, a page a person
edits in the desktop app, and a page a desktop doc syncs into the wiki all carry
the header the repo lint asks for.
"""

from __future__ import annotations

from posthog.dataclasses import frozen

# The statuses the repo lint accepts on a page.
STATUS_ACTIVE = "active"
STATUS_SUPERSEDED = "superseded"
STATUS_HISTORICAL = "historical"

# A desktop doc has its own vocabulary, so the sync states the mapping once.
DOC_STATUS_TO_PAGE_STATUS = {
    "draft": STATUS_ACTIVE,
    "active": STATUS_ACTIVE,
    "done": STATUS_HISTORICAL,
}


@frozen
class SpacePageHeader:
    """The frontmatter of a page that belongs to one space.

    ``doc_id`` is set when the page came from a desktop doc: the sync needs to
    find the page it wrote last time, and the lint ignores extra fields.
    """

    team_id: int
    channel_id: str
    summary: str
    status: str = STATUS_ACTIVE
    sources: str = "channel-catalog"
    doc_id: str | None = None


def render_frontmatter(fields: dict[str, str]) -> str:
    body = "".join(f"{key}: {value}\n" for key, value in fields.items())
    return f"---\n{body}---\n"


def render_space_page(header: SpacePageHeader, title: str, body: str = "") -> str:
    """A space page as one string, ready to write."""
    fields: dict[str, str] = {
        "team_id": str(header.team_id),
        "channel_id": header.channel_id,
        "summary": " ".join(header.summary.split()),
        "status": header.status,
        "sources": header.sources,
    }
    if header.doc_id:
        fields["doc_id"] = header.doc_id
    written = body.strip()
    tail = f"\n{written}\n" if written else ""
    return f"{render_frontmatter(fields)}\n# {title}\n{tail}"


def page_status_for_doc_status(doc_status: str) -> str:
    """The page status a desktop doc's status becomes in the wiki."""
    return DOC_STATUS_TO_PAGE_STATUS.get(doc_status, STATUS_ACTIVE)


def doc_page_header(team_id: int, channel_id: str, doc_id: str, title: str, doc_status: str) -> SpacePageHeader:
    """The frontmatter a desktop doc's page carries in the wiki."""
    return SpacePageHeader(
        team_id=team_id,
        channel_id=channel_id,
        summary=f"Page: {' '.join(title.split()) or 'Untitled'}.",
        status=page_status_for_doc_status(doc_status),
        sources="desktop-doc",
        doc_id=doc_id,
    )
