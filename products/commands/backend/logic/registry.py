"""Binds each command declared in ``schema.py`` to the handler that runs it.

To add a command, declare it in ``schema.py``, write a handler that calls the target product's
facade, then bind the two here. Dispatch applies every check before the handler runs.
"""

from collections.abc import Callable, Mapping
from typing import Any

from posthog.dataclasses import frozen

from .commands import SUBJECT_NAMES, Answer, CommandContext, CommandOutcome, CommandTarget, SubjectKind, SubjectRef
from .handlers import (
    handle_assign,
    handle_loop,
    handle_qa,
    handle_resolve,
    handle_review,
    handle_stamp,
    review_target,
    stamp_target,
)
from .schema import (
    ASSIGN,
    COMMAND_DECLARATIONS,
    LOOP,
    QA,
    RESOLVE,
    REVIEW,
    STAMP,
    ArgumentError,
    CommandDeclaration,
    help_table,
    parse_arguments,
)


@frozen
class Invocation[A]:
    """A command whose arguments parsed, ready to run once dispatch has the context."""

    spec: "CommandSpec[A]"
    args: A

    def run(self, context: CommandContext) -> CommandOutcome:
        return self.spec.handler(context, self.args)


@frozen
class CommandSpec[A]:
    declaration: CommandDeclaration[A]
    handler: Callable[[CommandContext, A], CommandOutcome]
    # Names the projects the command's product acts in, out of the rolled-out candidates, before
    # dispatch checks membership and access. Without one, every candidate counts.
    target: Callable[[SubjectRef, tuple[int, ...]], CommandTarget | Answer] | None = None

    def parse(self, raw_argument: str) -> Invocation[A] | ArgumentError:
        args = parse_arguments(self.declaration, raw_argument)
        if isinstance(args, ArgumentError):
            return args
        return Invocation(spec=self, args=args)


def _index(specs: tuple[CommandSpec[Any], ...]) -> Mapping[str, CommandSpec[Any]]:
    """Specs by canonical verb. Raises ValueError unless every declaration has exactly one handler."""
    bound = [spec.declaration.verb for spec in specs]
    declared = [declaration.verb for declaration in COMMAND_DECLARATIONS]
    if sorted(bound) != sorted(declared):
        raise ValueError(f"Bind each declared command to one handler: declared {declared}, bound {bound}")
    return {spec.declaration.verb: spec for spec in specs}


COMMANDS: Mapping[str, CommandSpec[Any]] = _index(
    (
        CommandSpec(declaration=REVIEW, handler=handle_review, target=review_target),
        CommandSpec(declaration=STAMP, handler=handle_stamp, target=stamp_target),
        CommandSpec(declaration=QA, handler=handle_qa),
        CommandSpec(declaration=LOOP, handler=handle_loop),
        CommandSpec(declaration=RESOLVE, handler=handle_resolve),
        CommandSpec(declaration=ASSIGN, handler=handle_assign),
    )
)


def help_text(subject_kind: SubjectKind) -> str:
    return f"Commands you can use on {SUBJECT_NAMES[subject_kind]}:\n\n{help_table(subject_kind)}"
