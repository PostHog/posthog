"""
Per-serializer body fixtures for the auto-IDOR parametrics.

Used by:
  - `test_cross_tenant_fk_in_post` (Phase 5b — POST list URL)
  - `test_cross_tenant_id_in_action` (Phase 5c — @action body)

When the generic `body_factory.build_minimal_post_body` introspection
can't satisfy a serializer's `validate()` or shape constraints, register
a per-serializer factory here. Action request serializers — pulled from
`@extend_schema(request=...)` via drf-spectacular introspection — are
keyed the same way as ModelSerializer POST bodies; the registry doesn't
distinguish, since the lookup is by serializer class identity.

Each factory takes the attacker's `team` and returns a `dict` ready to
pass as the request body. Reuse the existing `current_sentinel()` from
`factory.py` for string fields so info-leak detection still works.

Workflow for converting a skip → run:
  1. Run the parametric, find a `BodyUnfillable` skip with a serializer name.
  2. Locate the serializer's `validate()`/shape constraints in the source.
  3. Register a factory below that returns a body satisfying those constraints.
  4. Re-run; verify the test now executes (pass or fail) instead of skipping.
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
