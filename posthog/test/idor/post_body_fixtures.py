"""
Per-viewset POST body fixtures for the auto-IDOR `test_cross_tenant_fk_in_post`.

Mirrors `fixtures.py` (model instance factories) but for POST bodies.
When the generic `body_factory.build_minimal_post_body` introspection
can't satisfy a serializer's `validate()` or shape constraints, register
a per-serializer factory here.

Factories are keyed by the serializer class itself (not its model)
because two viewsets can share a model but need different body shapes,
and serializer Meta classes are unambiguous.

Each factory takes the attacker's `team` and returns a `dict` ready to
pass as the POST body. Reuse the existing `current_sentinel()` from
`factory.py` for string fields so info-leak detection still works.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from rest_framework import serializers

from posthog.models.team import Team

PostBodyFactory = Callable[[Team], dict[str, Any]]

_REGISTRY: dict[type[serializers.Serializer], PostBodyFactory] = {}


def register_post_body(serializer_cls: type[serializers.Serializer], factory: PostBodyFactory) -> None:
    """Associate a body factory with a serializer."""
    _REGISTRY[serializer_cls] = factory


def get_post_body_fixture(
    serializer_cls: type[serializers.Serializer],
) -> PostBodyFactory | None:
    return _REGISTRY.get(serializer_cls)


# ---------------------------------------------------------------------------
# Hand-written body fixtures — register hard cases below as the parametric
# uncovers them. Lazy imports keep this module importable without Django
# bootstrap when none of the registered factories are needed.
# ---------------------------------------------------------------------------


def _message_template_body(team: Team) -> dict[str, Any]:
    # MessageTemplateSerializer.validate() requires content.email.subject
    # when type='email'. Pick type='generic' so we don't trip the validator.
    return {
        "name": "idor-template",
        "description": "idor",
        "type": "generic",
    }


def _register_known_factories() -> None:
    """Lazy registration so importing this module doesn't pull product code."""
    try:
        from products.messaging.backend.api.message_templates import MessageTemplateSerializer

        register_post_body(MessageTemplateSerializer, _message_template_body)
    except Exception:
        pass


_register_known_factories()
