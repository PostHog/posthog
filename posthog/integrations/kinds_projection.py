"""Render `kinds_generated.py`, the typed accessors of the integrations SDK, from `catalogue.py`.

A renderer in the projection registry (`tools/hogli-commands/hogli_commands/projections.py`). Run
`hogli build:projections --only integration-kinds` after a change to the catalogue.

Each kind gets a class with one attribute per auth type that it supports, plus `any`. So mypy rejects
an auth type that a kind does not support, for example `IntegrationManager.github.credentials`.
"""

from posthog.integrations.catalogue import KINDS
from posthog.integrations.contracts import KindSpec
from posthog.integrations.enums import AuthType

OUTPUT = "posthog/integrations/kinds_generated.py"

HEADER = '''"""Generated from `posthog/integrations/catalogue.py`. Do not edit by hand.

Run `hogli build:projections --only integration-kinds` after a change to the catalogue. Import
`IntegrationManager` from `posthog.integrations`, not the classes here.
"""

from enum import StrEnum

from posthog.integrations.accessors import (
    AuthAccessor,
    IntegrationManagerBase,
    IntegrationReader,
    KindAccessor,
    OAuthAccessor,
)
from posthog.integrations.enums import AuthType
'''


def _attribute(kind: str) -> str:
    return kind.replace("-", "_")


def _class_name(kind: str) -> str:
    return "".join(part.capitalize() for part in kind.split("-")) + "Kind"


def _kind_class(kind: str, spec: KindSpec) -> list[str]:
    lines = ["", "", f"class {_class_name(kind)}(KindAccessor):", f'    kind = "{kind}"']
    for auth_type in AuthType:
        if auth_type not in spec.supported:
            continue
        note = "  # the default" if auth_type == spec.default else ""
        if auth_type == AuthType.OAUTH:
            lines.append(f'    oauth = OAuthAccessor(kind="{kind}"){note}')
        else:
            lines.append(
                f'    {auth_type.value} = AuthAccessor(kind="{kind}", auth_type=AuthType.{auth_type.name}){note}'
            )
    lines.append(f'    any = IntegrationReader(kinds=frozenset({{"{kind}"}}))')
    return lines


def render_kinds() -> str:
    kinds = sorted(KINDS.items())
    # A plain StrEnum: the OpenAPI enum names come from the model's `Integration.IntegrationKind`, and a
    # second labeled class with the same name would make both names ambiguous.
    lines = [HEADER, "", "class IntegrationKind(StrEnum):"]
    lines += [f'    {_attribute(kind).upper()} = "{kind}"' for kind, _ in kinds]
    for kind, spec in kinds:
        lines += _kind_class(kind, spec)
    lines += ["", "", "class GeneratedIntegrationManager(IntegrationManagerBase):"]
    lines += [f"    {_attribute(kind)} = {_class_name(kind)}()" for kind, _ in kinds]
    return "\n".join(lines) + "\n"


def render() -> dict[str, str]:
    return {OUTPUT: render_kinds()}
