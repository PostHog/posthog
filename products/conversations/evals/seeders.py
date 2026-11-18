"""Install the invented BK corpus and one ticket into a team."""

from __future__ import annotations

from uuid import NAMESPACE_URL, uuid4, uuid5

from posthog.dataclasses import frozen
from posthog.models import Organization, OrganizationMembership, Team, User
from posthog.models.comment import Comment
from posthog.models.scoping import team_scope

from products.business_knowledge.backend.logic import create_text_source
from products.business_knowledge.backend.models import KnowledgeChunk, KnowledgeDocument, SafetyVerdict
from products.conversations.backend.models import Ticket
from products.conversations.evals.corpus import CORPUS
from products.conversations.evals.fixtures import SupportReplyFixture


@frozen
class SeededCase:
    team_id: int
    user_id: int
    ticket_id: str
    chunks_by_source: dict[str, tuple[str, ...]]
    source_by_chunk: dict[str, str]


@frozen
class EvalTeam:
    organization: Organization
    team: Team
    user: User


def provision_eval_team(*, label: str) -> EvalTeam:
    suffix = f"{label}-{uuid4().hex[:8]}"
    organization = Organization.objects.create(name=f"Acme Capture eval {suffix}")
    user = User.objects.create_and_join(
        organization=organization,
        email=f"eval-{suffix}@example.com",
        password=None,
        first_name="Eval",
        level=OrganizationMembership.Level.OWNER,
    )
    team = Team.objects.create(organization=organization, name=f"Acme Capture {suffix}")
    return EvalTeam(organization=organization, team=team, user=user)


def seed_corpus(*, team_id: int, created_by_id: int) -> dict[str, tuple[str, ...]]:
    """Write every corpus document and mark them SAFE so search can see them."""
    chunks_by_source: dict[str, tuple[str, ...]] = {}
    for document in CORPUS:
        create_text_source(
            team_id=team_id,
            created_by_id=created_by_id,
            name=document.name,
            text=document.text,
            always_include=document.always_include,
        )
    with team_scope(team_id, canonical=True):
        KnowledgeDocument.objects.filter(team_id=team_id).update(safety_verdict=SafetyVerdict.SAFE)
        for chunk in KnowledgeChunk.objects.filter(team_id=team_id).select_related("source"):
            chunks_by_source.setdefault(chunk.source.name, ())
            chunks_by_source[chunk.source.name] = (*chunks_by_source[chunk.source.name], str(chunk.id))
    return chunks_by_source


def seed_ticket(*, team: Team, fixture: SupportReplyFixture) -> Ticket:
    session_id = str(uuid5(NAMESPACE_URL, f"support-reply-eval:{fixture.name}"))
    ticket = Ticket.objects.create_with_number(
        team=team,
        widget_session_id=session_id,
        distinct_id=f"eval-person-{fixture.name}",
        channel_source="widget",
        session_context={"current_url": "https://app.example.com/support"},
    )
    Comment.objects.create(
        team=team,
        scope="conversations_ticket",
        item_id=str(ticket.id),
        content=fixture.prompt,
        item_context={"author_type": "customer", "is_private": False},
    )
    return ticket


def seed_case(*, eval_team: EvalTeam, fixture: SupportReplyFixture) -> SeededCase:
    if fixture.docs_source:
        settings = dict(eval_team.team.conversations_settings or {})
        settings["docs_source"] = fixture.docs_source
        eval_team.team.conversations_settings = settings
        eval_team.team.save(update_fields=["conversations_settings"])
    chunks_by_source = seed_corpus(team_id=eval_team.team.id, created_by_id=eval_team.user.id)
    ticket = seed_ticket(team=eval_team.team, fixture=fixture)
    source_by_chunk = {
        chunk_id: source_name for source_name, chunk_ids in chunks_by_source.items() for chunk_id in chunk_ids
    }
    return SeededCase(
        team_id=eval_team.team.id,
        user_id=eval_team.user.id,
        ticket_id=str(ticket.id),
        chunks_by_source=chunks_by_source,
        source_by_chunk=source_by_chunk,
    )


def teardown_eval_team(*, eval_team: EvalTeam) -> None:
    user_id = eval_team.user.id
    eval_team.organization.delete()
    User.objects.filter(id=user_id).delete()
