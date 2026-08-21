"""Serializers and write helpers for the GitHub issues and PRs linked to a ticket."""

from uuid import UUID

from django.db import IntegrityError, transaction

from rest_framework import serializers

from posthog.api.shared import UserBasicSerializer
from posthog.exceptions_capture import capture_exception
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.user import User

from products.conversations.backend.github_link_metadata import apply_github_link_metadata, fetch_github_link_metadata
from products.conversations.backend.github_references import GithubReference, parse_github_reference
from products.conversations.backend.models import Ticket, TicketGithubLink, TicketGithubLinkType


class TicketGithubLinkSerializer(serializers.ModelSerializer):
    url = serializers.URLField(
        read_only=True, help_text="Canonical https://github.com URL of the issue or pull request."
    )
    created_by = UserBasicSerializer(read_only=True, allow_null=True)

    class Meta:
        model = TicketGithubLink
        fields = ["id", "repo", "number", "link_type", "url", "title", "link_state", "created_by", "created_at"]
        read_only_fields = fields
        extra_kwargs = {
            "repo": {"help_text": "Repository in owner/name form."},
            "number": {"help_text": "Issue or pull request number within the repository."},
            "link_type": {"help_text": "Whether the link points at an issue or a pull request."},
            "title": {
                "help_text": "Issue or PR title from GitHub. Null when no GitHub integration in the project can see the repository."
            },
            "link_state": {
                "help_text": "open, closed, or merged (pull requests only). Null when not fetched from GitHub."
            },
        }


class TicketGithubLinkCreateSerializer(serializers.Serializer):
    url = serializers.CharField(
        max_length=2048,
        help_text=(
            "A GitHub issue or pull request, as a URL (https://github.com/owner/repo/issues/123) "
            "or shorthand (owner/repo#123)."
        ),
    )

    def validate_url(self, value: str) -> GithubReference:
        reference = parse_github_reference(value)
        if reference is None:
            raise serializers.ValidationError(
                "Enter a GitHub issue or pull request URL, like https://github.com/owner/repo/issues/123, "
                "or owner/repo#123."
            )
        return reference


def link_github_reference(
    ticket: Ticket, reference: GithubReference, *, user: User | None
) -> tuple[TicketGithubLink, bool]:
    """Attach the reference to the ticket. Returns (link, created); re-linking an existing pair is a no-op.

    Title, state, and (for shorthand input) the issue-vs-PR type come from GitHub when an integration
    in the project can see the repo; otherwise the link is stored bare, typed as an issue.
    """
    existing = TicketGithubLink.objects.filter(ticket=ticket, repo=reference.repo, number=reference.number).first()
    if existing is not None:
        return existing, False

    link = TicketGithubLink(
        team_id=ticket.team_id,
        ticket=ticket,
        repo=reference.repo,
        number=reference.number,
        link_type=reference.link_type or TicketGithubLinkType.ISSUE,
        created_by=user,
    )
    apply_github_link_metadata(link, fetch_github_link_metadata(ticket.team_id, reference.repo, reference.number))
    try:
        with transaction.atomic():
            link.save()
    except IntegrityError:
        # Lost a race with an identical concurrent link: the unique constraint already holds the row.
        return TicketGithubLink.objects.get(ticket=ticket, repo=reference.repo, number=reference.number), False
    return link, True


def log_github_link_activity(
    *,
    organization_id: UUID,
    ticket: Ticket,
    link: TicketGithubLink,
    user: User,
    was_impersonated: bool,
    linked: bool,
) -> None:
    change = Change(
        type="Ticket",
        field="github_link",
        before=None if linked else link.url,
        after=link.url if linked else None,
        action="created" if linked else "deleted",
    )
    try:
        log_activity(
            organization_id=organization_id,
            team_id=ticket.team_id,
            user=user,
            was_impersonated=was_impersonated,
            item_id=str(ticket.id),
            scope="Ticket",
            activity="updated",
            detail=Detail(name=f"Ticket #{ticket.ticket_number}", changes=[change]),
        )
    except Exception as e:
        capture_exception(e, {"ticket_id": str(ticket.id)})
