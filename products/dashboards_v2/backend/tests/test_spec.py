import copy
from typing import Any

import pytest

from products.dashboards_v2.backend.facade.spec import (
    SpecValidationError,
    display_of,
    parse_draft,
    parse_publish,
    to_document,
)


def _document() -> dict[str, Any]:
    return {
        "uid": "checkout_health",
        "title": "Checkout health",
        "display": "spacious",
        "variables": [{"name": "region", "type": "custom", "options": ["eu", "us"], "current": "eu"}],
        "layout": {
            "type": "grid",
            "items": [
                {"panel": "orders", "x": 0, "y": 0, "w": 12, "h": 6},
                {"row": "Errors", "y": 6, "items": [{"panel": "errors", "x": 0, "y": 0, "w": 24, "h": 8}]},
                {
                    "tabs": "Detail",
                    "y": 14,
                    "items": [{"title": "Notes", "items": [{"panel": "notes", "x": 0, "y": 0, "w": 24, "h": 4}]}],
                },
            ],
        },
        "panels": {
            "orders": {
                "title": "Orders",
                "viz": {"type": "stat", "options": {"reduce": "last"}},
                "targets": [{"refId": "A", "language": "hogql", "query": "SELECT count() FROM events", "hide": True}],
                "transforms": [{"type": "math", "as": "rate", "expression": "$A / 60"}],
                "fieldConfig": {"softMin": 0, "mappings": [{"from": 0, "to": 10, "color": "red"}]},
            },
            "errors": {
                "viz": {"type": "timeseries"},
                "targets": [{"refId": "A", "language": "promql", "query": "sum(rate(errors_total[5m]))"}],
                "drilldowns": [{"title": "Zoom in", "action": {"type": "zoom"}}],
            },
            "notes": {"viz": {"type": "text", "options": {"markdown": "Owned by payments."}}},
        },
    }


def test_publish_round_trips_json_keys_and_fills_defaults() -> None:
    stored = to_document(parse_publish(_document()))

    expected = _document()
    expected["time"] = {"from": "now-6h", "to": "now"}
    expected["layout"]["columns"] = 24
    assert stored == expected
    assert display_of(stored) == "spacious"


def test_publish_drops_unknown_keys_but_keeps_free_form_options() -> None:
    document = _document()
    document["projectId"] = 2
    document["panels"]["orders"]["viz"]["options"]["sparkline"] = {"show": True}

    stored = to_document(parse_publish(document))

    assert "projectId" not in stored
    assert stored["panels"]["orders"]["viz"]["options"]["sparkline"] == {"show": True}


def _dangling_panel(d: dict[str, Any]) -> None:
    d["layout"]["items"].append({"panel": "ghost", "x": 0, "y": 20, "w": 6, "h": 4})


def _unplaced_panel(d: dict[str, Any]) -> None:
    d["panels"]["spare"] = {"viz": {"type": "text"}}


def _placed_twice(d: dict[str, Any]) -> None:
    d["layout"]["items"].append({"panel": "orders", "x": 12, "y": 0, "w": 12, "h": 6})


def _duplicate_variable(d: dict[str, Any]) -> None:
    d["variables"].append({"name": "region", "type": "textbox"})


def _unknown_viz(d: dict[str, Any]) -> None:
    d["panels"]["notes"]["viz"]["type"] = "sparkle"


def _no_queries(d: dict[str, Any]) -> None:
    d["panels"]["errors"]["targets"] = []


def _spills_past_grid(d: dict[str, Any]) -> None:
    d["layout"]["items"][1]["items"][0]["x"] = 6


def _bad_uid(d: dict[str, Any]) -> None:
    d["uid"] = "Checkout Health"


def _unknown_variable_type(d: dict[str, Any]) -> None:
    d["variables"][0]["type"] = "slider"


@pytest.mark.parametrize(
    "break_document, path, message",
    [
        (_dangling_panel, "layout", 'unknown panel "ghost"'),
        (_unplaced_panel, "panels.spare", "not placed"),
        (_placed_twice, "layout", "placed twice"),
        (_duplicate_variable, "variables", 'duplicate variable "region"'),
        (_unknown_viz, "panels.notes.viz.type", 'unknown viz type "sparkle"'),
        (_no_queries, "panels.errors.targets", "has no queries"),
        (_spills_past_grid, 'layout.row "Errors"', "spills past column 24"),
        (_bad_uid, "uid", "pattern"),
        (_unknown_variable_type, "variables.0", "slider"),
    ],
)
def test_publish_rejects_invalid_documents(break_document: Any, path: str, message: str) -> None:
    document = _document()
    break_document(document)

    with pytest.raises(SpecValidationError) as error:
        parse_publish(document)

    assert any(issue.path == path and message in issue.message for issue in error.value.issues), error.value.issues


def test_draft_keeps_a_broken_document_that_has_a_uid() -> None:
    document = copy.deepcopy(_document())
    document["panels"]["orders"] = {"viz": "not an object"}
    document["layout"] = None

    draft = parse_draft(document)

    assert draft.model_dump() == document
    with pytest.raises(SpecValidationError):
        parse_publish(document)


@pytest.mark.parametrize("document", [{"title": "No uid"}, ["uid"], None])
def test_draft_requires_an_object_with_a_uid(document: Any) -> None:
    with pytest.raises(SpecValidationError):
        parse_draft(document)
