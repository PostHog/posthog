"""The grammar of the `@posthog` pull request commands, declared once.

Each command declares its arguments as a frozen dataclass. Dispatch parses comments against that
declaration, and the help reply, the README command table and the generated command signature all
render from it, so the spelling of a verb or an option exists only here.

Grammar:

- Options come first. A flag is `--name`. A valued option is `--name value` or `--name=value`.
- Option scanning stops at the first token that does not start with `--`. The rest of the comment
  line is the command's one free-text field, kept as typed.
- A lone `--` also stops option scanning, so free text can start with `--`.
- An option typed with one dash, such as `—deep`, counts as `--deep`: text editors such as macOS
  autocorrect turn a typed `--` into a dash.
- Comment text is never split with `shlex`, because apostrophes and unbalanced quotes are normal
  in prose.

This module stays free of Django and of other products, because the projection renderer loads it
outside Django.
"""

import re
import types
import dataclasses
import unicodedata
from collections.abc import Mapping
from typing import Any, Literal, Union, get_args, get_origin, get_type_hints

from posthog.dataclasses import frozen
from posthog.scopes import APIScopeObject

from .commands import SUBJECT_NAMES, SubjectKind

SCHEMA_VERSION = 1

MENTION = "@posthog"
# A line with the bare mention asks for help, so the grammar owns this verb.
HELP_VERB = "help"
MAX_ARGUMENT_LENGTH = 200

AccessLevel = Literal["viewer", "editor", "manager"]
OptionKind = Literal["flag", "value"]

_ROLE = "github_command_role"
_HELP = "github_command_help"
_REQUIRED = "github_command_required"
_NAME_RE = re.compile(r"[a-z][a-z0-9_]*")
_VERB_RE = re.compile(r"[a-z][a-z0-9-]*")
_TOKEN_RE = re.compile(r"\S+")
_END_OF_OPTIONS = "--"
_DASHED_OPTION_RE = re.compile(r"^[\u2013\u2014](?=[a-z])")


def flag(help: str) -> Any:
    """A boolean option, off unless the comment names it."""
    return dataclasses.field(default=False, metadata={_ROLE: "flag", _HELP: help})


def option(help: str, *, default: str | None = None) -> Any:
    """An option that takes one value. Annotate the field as `Literal[...]` to limit the values."""
    return dataclasses.field(default=default, metadata={_ROLE: "value", _HELP: help})


def text(help: str, *, required: bool = False) -> Any:
    """The free text after the options, kept as typed. A command has at most one."""
    return dataclasses.field(default="", metadata={_ROLE: "text", _HELP: help, _REQUIRED: required})


def sanitize_argument(raw: str) -> str:
    """Make the free text after the verb safe to store, log and hand to a product.

    Drops control and format characters, which removes bidirectional overrides and zero-width
    characters that can make text read differently than it runs. Collapses whitespace and caps
    the length, so an argument stays one short line.
    """
    kept = "".join(char for char in raw if unicodedata.category(char)[0] != "C" or char in " \t\r\n")
    collapsed = " ".join(kept.split())
    return collapsed[:MAX_ARGUMENT_LENGTH]


@frozen
class StampArgs:
    pass


@frozen
class ReviewArgs:
    deep: bool = flag("Run a Deep review instead of the default Standard review.")
    no_resolve: bool = flag(
        "Don't resolve review comments after a Deep review. By default the pull request owner's setting decides."
    )


@frozen
class QaArgs:
    focus: str = text("What to focus on. The agent gets it as your instruction.")


@frozen
class LoopArgs:
    name: str = text("The loop's name.", required=True)


@frozen
class ResolveArgs:
    pass


@frozen
class AssignArgs:
    pass


@frozen
class HelpArgs:
    pass


@frozen
class OptionGrammar:
    name: str
    spelling: str
    kind: OptionKind
    choices: tuple[str, ...] | None
    default: bool | str | None
    help: str


@frozen
class TextGrammar:
    name: str
    required: bool
    help: str


@frozen
class Grammar:
    options: tuple[OptionGrammar, ...]
    text: TextGrammar | None


@frozen
class ResourceAccess:
    """A PostHog access-control resource the commenter needs on a project for the command."""

    resource: APIScopeObject
    level: AccessLevel


@frozen
class ArgumentError:
    """The arguments do not match the command's grammar, so nothing runs.

    The reason is built from the declaration only and never repeats the comment, so a reply cannot
    be made to post text the commenter wrote.
    """

    reason: str


def _choices(annotation: object) -> tuple[str, ...] | None:
    if get_origin(annotation) is not Literal:
        return None
    choices = get_args(annotation)
    if not choices or not all(isinstance(choice, str) for choice in choices):
        raise ValueError(f"Literal choices must be strings, got {annotation!r}")
    return choices


def _without_none(annotation: object) -> tuple[object, bool]:
    """The annotation without `| None`, and whether `None` was part of it."""
    if get_origin(annotation) not in (Union, types.UnionType):
        return annotation, False
    members = [member for member in get_args(annotation) if member is not type(None)]
    if len(members) != 1 or len(members) == len(get_args(annotation)):
        raise ValueError(f"Only `X | None` unions are supported, got {annotation!r}")
    return members[0], True


def _option_grammar(field: dataclasses.Field[Any], annotation: object, role: str) -> OptionGrammar:
    if role == "flag":
        if annotation is not bool:
            raise ValueError(f"Flag `{field.name}` must be a bool")
        return OptionGrammar(
            name=field.name,
            spelling=_spelling(field.name),
            kind="flag",
            choices=None,
            default=False,
            help=field.metadata[_HELP],
        )
    value_type, optional = _without_none(annotation)
    choices = _choices(value_type)
    if value_type is not str and choices is None:
        raise ValueError(f"Option `{field.name}` must be str or Literal[str, ...], got {annotation!r}")
    default = field.default
    if default is dataclasses.MISSING:
        raise ValueError(f"Declare `{field.name}` with option(), which sets its default")
    if default is None and not optional:
        raise ValueError(f"Option `{field.name}` defaults to None, so its type must allow None")
    if choices is not None and default is not None and default not in choices:
        raise ValueError(f"Option `{field.name}` defaults to {default!r}, which is not one of {choices}")
    return OptionGrammar(
        name=field.name,
        spelling=_spelling(field.name),
        kind="value",
        choices=choices,
        default=default,
        help=field.metadata[_HELP],
    )


def _spelling(name: str) -> str:
    return "--" + name.replace("_", "-")


def derive_grammar(args_class: type) -> Grammar:
    """Read the grammar from an args dataclass. Raises ValueError for anything the parser cannot read."""
    if not dataclasses.is_dataclass(args_class):
        raise ValueError(f"{args_class.__name__} must be a dataclass")
    hints = get_type_hints(args_class)
    options: list[OptionGrammar] = []
    text_fields: list[TextGrammar] = []
    for field in dataclasses.fields(args_class):
        if not field.name.isascii() or not _NAME_RE.fullmatch(field.name):
            raise ValueError(f"Argument name must be lowercase ASCII, got {field.name!r}")
        role = field.metadata.get(_ROLE)
        if role is None:
            raise ValueError(f"Declare `{field.name}` with flag(), option() or text()")
        annotation = hints[field.name]
        if role == "text":
            if annotation is not str:
                raise ValueError(f"Text field `{field.name}` must be a str")
            text_fields.append(
                TextGrammar(name=field.name, required=field.metadata[_REQUIRED], help=field.metadata[_HELP])
            )
        else:
            options.append(_option_grammar(field, annotation, role))
    if len(text_fields) > 1:
        raise ValueError(f"{args_class.__name__} has more than one text field")
    return Grammar(options=tuple(options), text=text_fields[0] if text_fields else None)


@frozen
class CommandDeclaration[A]:
    verb: str
    summary: str
    args: type[A]
    # Shown in the generated docs. None for a command that dispatch answers itself.
    dispatches_to: str | None
    aliases: tuple[str, ...] = ()
    access: ResourceAccess | None = None
    subject_kinds: tuple[SubjectKind, ...] = ("pull_request",)
    # A fork's head is code nobody with write access has vetted. Commands that run or approve it
    # must refuse forks; only a command that reads nothing from the head may allow them.
    allows_forks: bool = False

    def __post_init__(self) -> None:
        for verb in (self.verb, *self.aliases):
            if not verb.isascii() or not _VERB_RE.fullmatch(verb):
                raise ValueError(f"Command verb must be one lowercase word, got {verb!r}")
        derive_grammar(self.args)


REVIEW = CommandDeclaration(
    verb="review",
    summary="Start a Standard review of this pull request.",
    args=ReviewArgs,
    dispatches_to="PostHog Review",
    access=ResourceAccess(resource="review_hog", level="editor"),
)
STAMP = CommandDeclaration(
    verb="stamp",
    summary="Ask Stamphog to review this pull request. Stamphog decides whether to approve.",
    args=StampArgs,
    dispatches_to="Stamphog",
    aliases=("approve",),
    access=ResourceAccess(resource="stamphog", level="editor"),
)
QA = CommandDeclaration(
    verb="qa",
    summary="Run frontend QA on this pull request in PostHog Code and post a report.",
    args=QaArgs,
    dispatches_to="PostHog Code",
    access=ResourceAccess(resource="task", level="editor"),
)
LOOP = CommandDeclaration(
    verb="loop",
    summary="Run one of your own Loops with this pull request as its input.",
    args=LoopArgs,
    dispatches_to="Loops",
    access=ResourceAccess(resource="loop", level="editor"),
)
RESOLVE = CommandDeclaration(
    verb="resolve",
    summary="Mark this error tracking issue as resolved.",
    args=ResolveArgs,
    dispatches_to="Error tracking",
    access=ResourceAccess(resource="error_tracking", level="editor"),
    subject_kinds=("error_tracking_issue",),
)
ASSIGN = CommandDeclaration(
    verb="assign",
    summary="Assign this error tracking issue to yourself.",
    args=AssignArgs,
    dispatches_to="Error tracking",
    access=ResourceAccess(resource="error_tracking", level="editor"),
    subject_kinds=("error_tracking_issue",),
)
# Answered by dispatch itself: it needs no PostHog account, project or pull request state.
HELP = CommandDeclaration(
    verb=HELP_VERB,
    summary="List these commands.",
    args=HelpArgs,
    dispatches_to=None,
    allows_forks=True,
    subject_kinds=get_args(SubjectKind),
)

COMMAND_DECLARATIONS: tuple[CommandDeclaration[Any], ...] = (REVIEW, STAMP, QA, LOOP, RESOLVE, ASSIGN)


def _canonical_verbs(declarations: tuple[CommandDeclaration[Any], ...]) -> Mapping[str, str]:
    """Every verb and alias, mapped to its canonical verb. Raises ValueError on a collision."""
    canonical: dict[str, str] = {}
    for declaration in declarations:
        for verb in (declaration.verb, *declaration.aliases):
            if verb in canonical or verb == HELP_VERB:
                raise ValueError(f"Command verb {verb!r} collides with another verb or alias")
            canonical[verb] = declaration.verb
    return canonical


_CANONICAL_VERBS = _canonical_verbs(COMMAND_DECLARATIONS)


def resolve_verb(verb: str) -> str | None:
    """The canonical verb for a verb or an alias, or None when no command has that name."""
    return _CANONICAL_VERBS.get(verb)


def _option_value(option: OptionGrammar, value: str) -> str | ArgumentError:
    if not value or value.startswith(_END_OF_OPTIONS):
        return ArgumentError(reason=f"`{option.spelling}` needs a value.")
    if option.choices is not None and value not in option.choices:
        allowed = ", ".join(f"`{choice}`" for choice in option.choices)
        return ArgumentError(reason=f"`{option.spelling}` must be one of {allowed}.")
    return value


def parse_arguments[A](declaration: CommandDeclaration[A], raw: str) -> A | ArgumentError:
    grammar = derive_grammar(declaration.args)
    options = {option.spelling: option for option in grammar.options}
    values: dict[str, object] = {}
    remainder = ""
    tokens = list(_TOKEN_RE.finditer(raw))
    index = 0
    while index < len(tokens):
        token = tokens[index]
        word = _DASHED_OPTION_RE.sub(_END_OF_OPTIONS, token.group())
        if word == _END_OF_OPTIONS:
            remainder = raw[token.end() :].strip()
            break
        if not word.startswith(_END_OF_OPTIONS):
            remainder = raw[token.start() :].strip()
            break
        spelling, has_inline_value, inline_value = word.partition("=")
        option = options.get(spelling)
        if option is None:
            return ArgumentError(reason=f"`{declaration.verb}` doesn't take that option.")
        if option.name in values:
            return ArgumentError(reason=f"Give `{option.spelling}` only once.")
        index += 1
        if option.kind == "flag":
            if has_inline_value:
                return ArgumentError(reason=f"`{option.spelling}` takes no value.")
            values[option.name] = True
            continue
        if has_inline_value:
            value = inline_value
        elif index < len(tokens):
            value = tokens[index].group()
            index += 1
        else:
            value = ""
        checked = _option_value(option, value)
        if isinstance(checked, ArgumentError):
            return checked
        values[option.name] = checked

    if grammar.text is None:
        if remainder:
            return ArgumentError(reason=f"`{declaration.verb}` takes no text.")
    elif grammar.text.required and not remainder:
        return ArgumentError(reason=f"`{declaration.verb}` needs a `<{grammar.text.name}>`.")
    else:
        values[grammar.text.name] = remainder
    return declaration.args(**values)


def _option_usage(option: OptionGrammar) -> str:
    if option.kind == "flag":
        return f"[{option.spelling}]"
    placeholder = "|".join(option.choices) if option.choices is not None else "value"
    return f"[{option.spelling} <{placeholder}>]"


def usage(declaration: CommandDeclaration[Any]) -> str:
    grammar = derive_grammar(declaration.args)
    parts = [MENTION, declaration.verb, *(_option_usage(option) for option in grammar.options)]
    if grammar.text is not None:
        placeholder = f"<{grammar.text.name}>"
        parts.append(placeholder if grammar.text.required else f"[{placeholder}]")
    return " ".join(parts)


def _command_signature(declaration: CommandDeclaration[Any]) -> dict[str, object]:
    grammar = derive_grammar(declaration.args)
    text_field = grammar.text
    return {
        "verb": declaration.verb,
        "aliases": list(declaration.aliases),
        "summary": declaration.summary,
        "dispatches_to": declaration.dispatches_to,
        "options": [
            {
                "name": option.name,
                "spelling": option.spelling,
                "kind": option.kind,
                "choices": list(option.choices) if option.choices is not None else None,
                "default": option.default,
                "help": option.help,
            }
            for option in grammar.options
        ],
        "text": (
            {"name": text_field.name, "required": text_field.required, "help": text_field.help, "verbatim": True}
            if text_field is not None
            else None
        ),
        "subject_kinds": list(declaration.subject_kinds),
        "refuses_forks": not declaration.allows_forks,
        "access": (
            {"resource": declaration.access.resource, "level": declaration.access.level}
            if declaration.access is not None
            else None
        ),
        "usage": usage(declaration),
    }


def signature() -> dict[str, object]:
    """The machine-readable command reference, checked in as `commands.generated.json`."""
    declarations = sorted((*COMMAND_DECLARATIONS, HELP), key=lambda declaration: declaration.verb)
    return {
        "schema_version": SCHEMA_VERSION,
        "prefix": MENTION,
        "commands": [_command_signature(declaration) for declaration in declarations],
    }


def _table_cell(value: str) -> str:
    # A pipe ends a Markdown table cell even inside a code span.
    return value.replace("|", "\\|")


def _what_it_does(declaration: CommandDeclaration[Any]) -> str:
    grammar = derive_grammar(declaration.args)
    parts = [declaration.summary]
    parts += [f"`{option.spelling}`: {option.help}" for option in grammar.options]
    if grammar.text is not None:
        parts.append(f"`<{grammar.text.name}>`: {grammar.text.help}")
    return " ".join(parts)


def help_table(subject_kind: SubjectKind | None = None) -> str:
    """The command table for the help reply and `COMMANDS.generated.md`.

    With a kind, it lists only the commands that act on it. Without one, it lists every command
    and what each works on.
    """
    declarations = [
        declaration
        for declaration in (*COMMAND_DECLARATIONS, HELP)
        if subject_kind is None or subject_kind in declaration.subject_kinds
    ]
    if subject_kind is not None:
        rows = ["| Command | Also | What it does |", "| --- | --- | --- |"]
    else:
        rows = ["| Command | Also | Works on | What it does |", "| --- | --- | --- | --- |"]
    for declaration in declarations:
        cells = [f"`{_table_cell(usage(declaration))}`", ", ".join(f"`{alias}`" for alias in declaration.aliases)]
        if subject_kind is None:
            cells.append(", ".join(SUBJECT_NAMES[kind] for kind in declaration.subject_kinds))
        cells.append(_table_cell(_what_it_does(declaration)))
        rows.append(f"| {' | '.join(cells)} |")
    return "\n".join(rows)
