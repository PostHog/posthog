import json

import pytest

from parameterized import parameterized
from rest_framework import serializers

from posthog.schema import AnyPropertyFilterDiscriminated

from products.ai_observability.backend.presentation.views.property_filters import (
    PropertyFiltersField,
    filters_need_query_scope,
)

EVENT_FILTER = {"type": "event", "key": "plan", "value": "enterprise", "operator": "exact"}


def _parse(value: str) -> tuple[AnyPropertyFilterDiscriminated, ...]:
    return PropertyFiltersField().run_validation(value)


@parameterized.expand(
    [
        ("not json", "{"),
        ("an object, not a list", json.dumps(EVENT_FILTER)),
        ("an unknown filter type", json.dumps([{"type": "telepathy", "key": "plan"}])),
        ("a filter missing its key", json.dumps([{"type": "event", "value": "enterprise"}])),
    ]
)
def test_rejects_what_is_not_a_list_of_filters(_name: str, value: str) -> None:
    with pytest.raises(serializers.ValidationError):
        _parse(value)


@parameterized.expand(
    [
        ("no filters", [], False),
        (
            "event and person filters",
            [EVENT_FILTER, {"type": "person", "key": "email", "value": "a@example.com", "operator": "exact"}],
            False,
        ),
        ("custom expression", [EVENT_FILTER, {"type": "hogql", "key": "1 = 1"}], True),
        ("data warehouse table", [{"type": "data_warehouse", "key": "amount", "value": 1, "operator": "gt"}], True),
        (
            "data warehouse person property",
            [{"type": "data_warehouse_person_property", "key": "stripe.plan", "value": "pro", "operator": "exact"}],
            True,
        ),
    ]
)
def test_flags_filters_that_reach_beyond_the_traces(
    _name: str, filters: list[dict[str, object]], expected: bool
) -> None:
    assert filters_need_query_scope(_parse(json.dumps(filters))) is expected
