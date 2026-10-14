"""Decides whether a command runs, then runs it. Every channel shares this path.

Every command passes the same steps, in this order, before its handler runs:

1. The channel admits the request: its rollout, deduplication, rate limit and its own check of who
   may ask. People who fail it get no answer at all, so the bot gives outsiders nothing to probe
   and no way to make it post. Everyone past it gets a reply that says what happened.
2. The request holds exactly one command, the command exists, and its arguments match its grammar.
3. The requester's linked PostHog accounts include one that is a member of a rolled-out candidate
   project of the subject. With several linked accounts, the handler picks the project, and the
   account that is a member of it acts there.
4. The subject allows the command, for example the pull request is open, and the command allows
   forks if the head is a fork.
5. The account has the access the command declares on the project, in PostHog access control.
"""

from typing import Any, Protocol

import structlog
from prometheus_client import Counter

from posthog.dataclasses import frozen
from posthog.egress.github.transport import GitHubRateLimitError
from posthog.exceptions_capture import capture_exception
from posthog.models.scoping.manager import resolve_effective_team_id
from posthog.models.team import Team
from posthog.models.user import User
from posthog.permissions import UserAccessControl

from .commands import Answer, CommandContext, CommandRequest, DispatchOutcome, ProjectMember
from .github import CommandGitHub, InstallationGitHub
from .identity import Requester, resolve_requester
from .registry import COMMANDS, CommandSpec, Invocation, help_text
from .schema import HELP_VERB, ArgumentError, ResourceAccess, resolve_verb, usage
from .subjects import PullRequestSubject

logger = structlog.get_logger(__name__)

COMMANDS_TOTAL = Counter(
    "posthog_commands_total",
    "Commands, by channel, command and what dispatch did with them",
    labelnames=["channel", "verb", "outcome"],
)


@frozen
class Admission:
    """A request the channel let through, with what the shared steps need from it."""

    # Projects on the installation in the channel's rollout, oldest integration first. A command
    # runs only in one of them.
    team_ids: tuple[int, ...]
    # A channel that already called GitHub passes its client. Otherwise dispatch makes one.
    github: CommandGitHub | None = None


class CommandChannel(Protocol):
    """Where a command came from, and where its answer goes."""

    name: str
    request: CommandRequest
    unlinked_message: str

    def admit(self) -> Admission | DispatchOutcome:
        """The checks that stay silent: nobody who fails one hears from the bot."""
        ...

    def linked_users(self) -> list[User]:
        """The active PostHog users linked to the requester, most recently linked first."""
        ...

    def reply(self, message: str) -> None: ...


class CommandDispatcher:
    def __init__(self, channel: CommandChannel) -> None:
        self._channel = channel

    def dispatch(self) -> DispatchOutcome:
        request = self._channel.request
        verb = resolve_verb(request.verb)
        spec = COMMANDS.get(verb) if verb is not None else None
        outcome = self._dispatch(spec)
        # Unknown verbs share one label value, so a request cannot mint a metric series. Aliases
        # count under their canonical verb.
        verb_label = spec.declaration.verb if spec else (HELP_VERB if request.verb == HELP_VERB else "unknown")
        COMMANDS_TOTAL.labels(channel=self._channel.name, verb=verb_label, outcome=outcome).inc()
        logger.info(
            "command_dispatched",
            channel=self._channel.name,
            verb=verb_label,
            outcome=outcome,
            repository=request.subject.repository,
            pr_number=request.subject.number,
        )
        return outcome

    def _dispatch(self, spec: CommandSpec[Any] | None) -> DispatchOutcome:
        admission = self._channel.admit()
        if not isinstance(admission, Admission):
            return admission
        github = admission.github or InstallationGitHub.for_installation(
            self._channel.request.subject.installation_id, admission.team_ids
        )
        if github is None:
            return "no_installation"

        command = self._runnable_command(spec)
        if isinstance(command, Answer):
            self._channel.reply(command.message)
            return command.outcome

        context = self._command_context(command.spec, admission.team_ids, github)
        if isinstance(context, Answer):
            self._channel.reply(context.message)
            return context.outcome
        return self._run(command, context)

    def _runnable_command(self, spec: CommandSpec[Any] | None) -> Invocation[Any] | Answer:
        """The command to run, or the answer to a request that needs no PostHog account: help, and
        requests with no runnable command."""
        request = self._channel.request
        if request.ambiguous:
            return Answer(outcome="ambiguous", message="Put one command in a comment, so it is clear which one to run.")
        if request.verb == HELP_VERB:
            return Answer(outcome="help", message=help_text())
        if spec is None:
            return Answer(outcome="unknown_command", message="I don't know that command.\n\n" + help_text())
        invocation = spec.parse(request.argument)
        if isinstance(invocation, ArgumentError):
            return Answer(outcome="invalid_arguments", message=f"{invocation.reason} Use `{usage(spec.declaration)}`.")
        return invocation

    def _command_context(
        self, spec: CommandSpec[Any], team_ids: tuple[int, ...], github: CommandGitHub
    ) -> CommandContext | Answer:
        request = self._channel.request
        declaration = spec.declaration
        requester = resolve_requester(self._channel.linked_users(), team_ids)
        if not isinstance(requester, Requester):
            if requester.reason == "refused":
                return Answer(outcome="account_refused", message="I can't run commands for your PostHog account.")
            return Answer(outcome="unlinked", message=self._channel.unlinked_message)
        members = requester.members
        if not members:
            return Answer(
                outcome="no_project",
                message="You aren't a member of a PostHog project that uses pull request commands on this repository.",
            )

        pull_request = PullRequestSubject(request.subject, github).facts(declaration)
        if isinstance(pull_request, Answer):
            return pull_request

        access = declaration.access
        if access is not None:
            members = _members_with_access(members, access)
            if not members:
                return Answer(
                    outcome="access_denied",
                    message=f"You need {access.level} access to {access.resource} in PostHog to use `{declaration.verb}`.",
                )
        return CommandContext(request=request, pull_request=pull_request, members=members)

    def _run(self, command: Invocation[Any], context: CommandContext) -> DispatchOutcome:
        verb = command.spec.declaration.verb
        try:
            outcome = command.run(context)
        except GitHubRateLimitError:
            self._channel.reply(
                "GitHub is limiting how fast PostHog can work on this repository. Try again in a few minutes."
            )
            return "failed"
        except Exception as error:
            capture_exception(error)
            logger.exception("command_failed", channel=self._channel.name, verb=verb)
            self._channel.reply(f"Something went wrong while running `{verb}`. Try again in a few minutes.")
            return "failed"
        self._channel.reply(outcome.message)
        return "accepted" if outcome.accepted else "refused"


def _members_with_access(members: tuple[ProjectMember, ...], access: ResourceAccess) -> tuple[ProjectMember, ...]:
    # Products keep their rows, and their access rules, on the parent project.
    effective_team_ids = {member.team_id: resolve_effective_team_id(member.team_id) for member in members}
    teams = Team.objects.in_bulk(set(effective_team_ids.values()))
    users = User.objects.in_bulk({member.user_id for member in members})

    def has_access(member: ProjectMember) -> bool:
        team = teams.get(effective_team_ids[member.team_id])
        if team is None:
            return False
        user = users[member.user_id]
        access_control = UserAccessControl(user=user, team=team, organization_id=str(team.organization_id))
        return access_control.check_access_level_for_resource(access.resource, access.level)

    return tuple(member for member in members if has_access(member))
