from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from posthog.models.team.team import Team
from posthog.models.utils import UUIDTModel

ALLOWED_FIELDS = {"event_name", "distinct_id"}
ALLOWED_OPERATORS = {"exact", "contains"}
NODE_TYPES = {"and", "or", "not", "condition"}
EXPECTED_RESULTS = {"drop", "ingest"}
MAX_TREE_DEPTH = 5
MAX_CONDITIONS = 20

DEFAULT_FILTER_TREE = {"type": "or", "children": []}


class EventFilterMode(models.TextChoices):
    DISABLED = "disabled"
    DRY_RUN = "dry_run"
    LIVE = "live"


class EventFilterConfig(UUIDTModel):
    """
    Per-team event filter configuration evaluated at ingestion time.
    One filter per team. Uses a boolean expression tree with AND, OR, NOT
    and condition nodes. If the tree evaluates to true, the event is dropped (live)
    or marked as would-be-dropped (dry_run).
    """

    team = models.OneToOneField(Team, on_delete=models.CASCADE, related_name="event_filter")
    mode = models.CharField(max_length=20, choices=EventFilterMode, default=EventFilterMode.DISABLED)
    filter_tree = models.JSONField(
        default=None,
        null=True,
        blank=True,
        help_text=(
            "Boolean expression tree. Nodes: "
            '{"type": "and"|"or", "children": [...]}, '
            '{"type": "not", "child": {...}}, '
            '{"type": "condition", "field": "event_name"|"distinct_id", '
            '"operator": "exact"|"contains", "value": "<string>"}'
        ),
    )
    test_cases = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "Test events to validate the filter. Each: "
            '{"event_name": "...", "distinct_id": "...", '
            '"expected_result": "drop"|"ingest"}'
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    def __str__(self) -> str:
        return f"EventFilterConfig(team={self.team_id}, mode={self.mode})"

    def clean(self) -> None:
        if self.filter_tree:
            validate_filter_tree(self.filter_tree)
        if self.test_cases:
            validate_test_cases(self.test_cases)
        if self.filter_tree and self.test_cases:
            failures = run_test_cases(self.filter_tree, self.test_cases)
            if failures:
                raise ValidationError({"test_cases": failures})

    def save(self, *args, **kwargs):
        if self.filter_tree:
            self.filter_tree = prune_filter_tree(self.filter_tree)
        self.clean()
        super().save(*args, **kwargs)


def prune_filter_tree(node: dict) -> dict | None:
    """Remove empty groups and collapse single-child groups."""
    node_type = node.get("type")

    if node_type == "condition":
        return node

    if node_type == "not":
        child = prune_filter_tree(node.get("child", {}))
        if child is None:
            return None
        return {**node, "child": child}

    if node_type in ("and", "or"):
        children = [prune_filter_tree(c) for c in node.get("children", [])]
        children = [c for c in children if c is not None]
        if len(children) == 0:
            return None
        if len(children) == 1:
            return children[0]
        return {**node, "children": children}

    return node


def _count_conditions(node: object) -> int:
    if not isinstance(node, dict):
        return 0
    node_type = node.get("type")
    if node_type == "condition":
        return 1
    if node_type == "not":
        return _count_conditions(node.get("child"))
    if node_type in ("and", "or"):
        return sum(_count_conditions(c) for c in node.get("children", []))
    return 0


def _check_max_depth(node: object, depth: int = 0) -> int:
    if not isinstance(node, dict):
        return depth
    node_type = node.get("type")
    if node_type == "not":
        return _check_max_depth(node.get("child"), depth + 1)
    if node_type in ("and", "or"):
        return max((_check_max_depth(c, depth + 1) for c in node.get("children", [])), default=depth)
    return depth


def _validate_node(node: object, path: str = "root") -> None:
    if not isinstance(node, dict):
        raise ValidationError({"filter_tree": f"Node at {path} must be an object."})

    node_type = node.get("type")
    if node_type not in NODE_TYPES:
        raise ValidationError(
            {"filter_tree": f"Node at {path}: type must be one of {sorted(NODE_TYPES)}, got '{node_type}'."}
        )

    if node_type == "condition":
        _validate_condition(node, path)
    elif node_type == "not":
        if "child" not in node:
            raise ValidationError({"filter_tree": f"Node at {path}: 'not' node must have a 'child'."})
        _validate_node(node["child"], f"{path}.child")
    elif node_type in ("and", "or"):
        children = node.get("children")
        if not isinstance(children, list):
            raise ValidationError({"filter_tree": f"Node at {path}: '{node_type}' node must have a 'children' list."})
        for i, child in enumerate(children):
            _validate_node(child, f"{path}.children[{i}]")


def validate_filter_tree(node: object) -> None:
    condition_count = _count_conditions(node)
    if condition_count > MAX_CONDITIONS:
        raise ValidationError({"filter_tree": f"Filter exceeds maximum of {MAX_CONDITIONS} conditions."})

    max_depth = _check_max_depth(node)
    if max_depth > MAX_TREE_DEPTH:
        raise ValidationError({"filter_tree": f"Tree exceeds maximum depth of {MAX_TREE_DEPTH}."})

    _validate_node(node)


def _validate_condition(node: dict, path: str) -> None:
    for key in ("field", "operator", "value"):
        if key not in node:
            raise ValidationError({"filter_tree": f"Condition at {path} missing required key '{key}'."})

    if node["field"] not in ALLOWED_FIELDS:
        raise ValidationError(
            {
                "filter_tree": f"Condition at {path}: field must be one of {sorted(ALLOWED_FIELDS)}, got '{node['field']}'."
            }
        )

    if node["operator"] not in ALLOWED_OPERATORS:
        raise ValidationError(
            {
                "filter_tree": f"Condition at {path}: operator must be one of {sorted(ALLOWED_OPERATORS)}, got '{node['operator']}'."
            }
        )

    if not isinstance(node["value"], str) or len(node["value"]) == 0:
        raise ValidationError({"filter_tree": f"Condition at {path}: value must be a non-empty string."})


def validate_test_cases(test_cases: object) -> None:
    if not isinstance(test_cases, list):
        raise ValidationError({"test_cases": "Must be a list."})

    for i, tc in enumerate(test_cases):
        if not isinstance(tc, dict):
            raise ValidationError({"test_cases": f"Test case {i} must be an object."})

        if "expected_result" not in tc:
            raise ValidationError({"test_cases": f"Test case {i} missing 'expected_result'."})

        if tc["expected_result"] not in EXPECTED_RESULTS:
            raise ValidationError({"test_cases": f"Test case {i}: expected_result must be 'drop' or 'ingest'."})

        for field in ("event_name", "distinct_id"):
            if field in tc and not isinstance(tc[field], str):
                raise ValidationError({"test_cases": f"Test case {i}: {field} must be a string."})


def run_test_cases(filter_tree: dict, test_cases: list[dict]) -> list[str]:
    """Run test cases against a filter tree. Returns a list of failure descriptions (empty if all pass)."""
    failures: list[str] = []
    for i, tc in enumerate(test_cases):
        event = {k: v for k, v in tc.items() if k != "expected_result"}
        should_drop = evaluate_filter_tree(filter_tree, event)
        actual = "drop" if should_drop else "ingest"
        expected = tc["expected_result"]
        if actual != expected:
            failures.append(f"Test case {i}: expected '{expected}' but got '{actual}' for {event}")
    return failures


def tree_has_conditions(node: object) -> bool:
    """Check if a filter tree contains at least one condition leaf."""
    if not isinstance(node, dict):
        return False
    node_type = node.get("type")
    if node_type == "condition":
        return True
    if node_type == "not":
        return tree_has_conditions(node.get("child"))
    if node_type in ("and", "or"):
        return any(tree_has_conditions(child) for child in node.get("children", []))
    return False


def evaluate_filter_tree(node: dict, event: dict) -> bool:
    """
    Evaluate a filter tree against an event dict. Returns True if the event should be dropped.

    SAFETY: Empty groups are conservative (never drop):
    - Empty AND returns False (not vacuous True from all([])) to avoid dropping all events
    - Empty OR returns False (no children match)
    Dropping is irreversible; not dropping just means unwanted events get through temporarily.
    """
    node_type = node.get("type")

    if node_type == "condition":
        field_value = event.get(node.get("field", ""))
        if field_value is None:
            return False
        operator = node.get("operator")
        target = node.get("value", "")
        if operator == "exact":
            return field_value == target
        elif operator == "contains":
            return target in field_value
        return False

    elif node_type == "and":
        children = node.get("children", [])
        return len(children) > 0 and all(evaluate_filter_tree(child, event) for child in children)

    elif node_type == "or":
        return any(evaluate_filter_tree(child, event) for child in node.get("children", []))

    elif node_type == "not":
        child = node.get("child")
        return not evaluate_filter_tree(child, event) if child is not None else False

    return False
