import uuid
from datetime import datetime

from posthog.dataclasses import frozen

from products.context_layer.backend import pages, store
from products.context_layer.backend.models import WikiPageProposal
from products.context_layer.backend.repo_lint import MAX_FILE_BYTES


@frozen
class WikiPageProposalDTO:
    id: uuid.UUID
    task_id: uuid.UUID
    path: str
    original_content: str
    content: str
    base_head: str
    created_at: datetime


def _proposal_dto(proposal: WikiPageProposal) -> WikiPageProposalDTO:
    return WikiPageProposalDTO(
        id=proposal.id,
        task_id=proposal.task_id,
        path=proposal.path,
        original_content=proposal.original_content,
        content=proposal.content,
        base_head=proposal.base_head,
        created_at=proposal.created_at,
    )


def create_page_proposal(
    organization_id: uuid.UUID,
    *,
    team_id: int,
    user_id: int,
    task_id: uuid.UUID,
    path: str,
    content: str,
    base_head: str,
) -> WikiPageProposalDTO:
    if not pages.is_run_content_path(path) or not path.startswith(("org/", "areas/", "decisions/")):
        raise pages.InvalidPagePathError("Propose an edit to an existing page under org/, areas/, or decisions/.")
    if pages.page_frontmatter_channel_id(content) is not None:
        raise pages.InvalidPagePathError("Shared wiki pages cannot declare channel_id frontmatter.")
    if len(content.encode("utf-8")) > MAX_FILE_BYTES:
        raise pages.InvalidPagePathError("The proposed page exceeds the wiki page size limit.")
    page = pages.get_page(organization_id, path)
    if page.head_sha != base_head:
        raise store.HeadConflictError(current_head=page.head_sha)
    with store.repo_writer_lock(organization_id):
        current_head = store.get_config(organization_id).head_sha
        if current_head != base_head:
            raise store.HeadConflictError(current_head=current_head)
        proposal = WikiPageProposal.objects.for_team(team_id).create(
            team_id=team_id,
            created_by_id=user_id,
            task_id=task_id,
            path=path,
            original_content=page.content,
            content=content,
            base_head=base_head,
        )
    return _proposal_dto(proposal)


def list_page_proposals(organization_id: uuid.UUID, user_id: int) -> list[WikiPageProposalDTO]:
    proposals = (
        WikiPageProposal.objects.unscoped()
        .filter(team__organization_id=organization_id, created_by_id=user_id, applied_head="")
        .order_by("-created_at")[:100]
    )
    return [_proposal_dto(proposal) for proposal in proposals]


def apply_page_proposal(
    organization_id: uuid.UUID, user_id: int, proposal_id: uuid.UUID, *, author: store.CommitAuthor
) -> str:
    try:
        # nosemgrep: idor-lookup-without-team (the organization and creator scope this cross-team review lookup)
        proposal = WikiPageProposal.objects.unscoped().get(
            id=proposal_id, team__organization_id=organization_id, created_by_id=user_id
        )
    except WikiPageProposal.DoesNotExist as error:
        raise pages.PageNotFoundError("This suggested edit is not available to you.") from error
    if proposal.applied_head:
        return proposal.applied_head
    head_sha = pages.write_page(
        organization_id,
        path=proposal.path,
        content=proposal.content,
        base_head=proposal.base_head,
        author=author,
    )
    WikiPageProposal.objects.for_team(proposal.team_id).filter(id=proposal.id).update(applied_head=head_sha)
    return head_sha
