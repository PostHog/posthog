"""
Parse `.semgrep/rules/idor-team-scoped-models.yaml` into tenant-scoped
model name sets.

The semgrep rule file is the single source of truth for which Django
models are tenant-scoped (team / organization / user / user+team). The
auto-IDOR framework re-uses that same list to decide whether a serializer
FK points at a tenant-scoped target — if it does, cross-tenant writes
must be blocked.

We intentionally parse the YAML rather than duplicating the model lists:
the semgrep CI check already keeps the YAML up-to-date, and mirroring it
here would drift.

Exposes four frozen sets of `str` (model class names, as written in the
regex alternation):

  - `TEAM_SCOPED_MODELS`
  - `ORG_SCOPED_MODELS`
  - `USER_SCOPED_MODELS`
  - `USER_AND_TEAM_SCOPED_MODELS`

And a helper:

  - `classify_model_scope(model_name)` -> scope literal or None
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal, Optional

import yaml

Scope = Literal["team", "organization", "user_in_org", "user_and_team"]

_YAML_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent / ".semgrep" / "rules" / "idor-team-scoped-models.yaml"
)

# Rules that carry the authoritative model allowlist for each scope. We
# pull from the taint rules (which have the fullest set); the lookup
# rules mirror them.
_TAINT_RULE_BY_SCOPE: dict[Scope, str] = {
    "team": "idor-taint-user-input-to-model-get",
    "organization": "idor-taint-user-input-to-org-model",
    "user_in_org": "idor-taint-user-input-to-user-model",
    "user_and_team": "idor-taint-user-input-to-user-team-model",
}


def _extract_model_names(verbose_regex: str) -> frozenset[str]:
    """Pull `Foo|Bar|Baz` alternatives out of a `(?x)(Foo|Bar|Baz)$` regex."""
    inner = re.sub(r"\(\?x\)\(", "", verbose_regex, count=1)
    inner = re.sub(r"\)\s*\$\s*$", "", inner)
    return frozenset(name.strip() for name in inner.split("|") if name.strip())


def _model_regex_for_rule(rules_data: dict, rule_id: str) -> Optional[str]:
    """Find the `$MODEL` metavariable-regex for a rule by id."""
    for rule in rules_data.get("rules", []):
        if rule.get("id") != rule_id:
            continue
        # The rule's model regex lives in a metavariable-regex entry where
        # metavariable == "$MODEL". Walk the rule tree and pull it.
        regex = _find_model_regex(rule)
        if regex:
            return regex
    return None


def _find_model_regex(node: object) -> Optional[str]:
    if isinstance(node, dict):
        if node.get("metavariable") == "$MODEL" and "regex" in node:
            regex = node["regex"]
            return regex if isinstance(regex, str) else None
        for value in node.values():
            found = _find_model_regex(value)
            if found:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _find_model_regex(item)
            if found:
                return found
    return None


def _load_scope_models() -> dict[Scope, frozenset[str]]:
    with _YAML_PATH.open("r", encoding="utf-8") as fh:
        rules_data = yaml.safe_load(fh)

    result: dict[Scope, frozenset[str]] = {}
    for scope, rule_id in _TAINT_RULE_BY_SCOPE.items():
        regex = _model_regex_for_rule(rules_data, rule_id)
        if regex is None:
            raise RuntimeError(f"Could not locate $MODEL regex for rule {rule_id!r} in {_YAML_PATH}")
        result[scope] = _extract_model_names(regex)
    return result


_SCOPE_MODELS = _load_scope_models()

TEAM_SCOPED_MODELS: frozenset[str] = _SCOPE_MODELS["team"]
ORG_SCOPED_MODELS: frozenset[str] = _SCOPE_MODELS["organization"]
USER_SCOPED_MODELS: frozenset[str] = _SCOPE_MODELS["user_in_org"]
USER_AND_TEAM_SCOPED_MODELS: frozenset[str] = _SCOPE_MODELS["user_and_team"]


def classify_model_scope(model_name: str) -> Optional[Scope]:
    """Return the tenant scope a model belongs to, or None if not tenant-scoped.

    When a model appears in both team-scoped and user+team-scoped lists,
    prefer the narrower `user_and_team` classification so downstream tests
    pick the right cross-tenant fixture.
    """
    if model_name in USER_AND_TEAM_SCOPED_MODELS:
        return "user_and_team"
    if model_name in TEAM_SCOPED_MODELS:
        return "team"
    if model_name in ORG_SCOPED_MODELS:
        return "organization"
    if model_name in USER_SCOPED_MODELS:
        return "user_in_org"
    return None


_ALL_TENANT_SCOPED: frozenset[str] = (
    TEAM_SCOPED_MODELS | ORG_SCOPED_MODELS | USER_SCOPED_MODELS | USER_AND_TEAM_SCOPED_MODELS
)


def lookup_tenant_models_by_partial_name(thing: str) -> list[str]:
    """Match a snake_cased `<thing>` (e.g. 'template') to tenant-scoped model names.

    Used by name-pattern detection on serializers that don't have a
    `Meta.model` to resolve against. Returns all plausible matches:

    1. **Exact PascalCase** — `feature_flag` → `[FeatureFlag]`. Cheapest,
       least ambiguous.
    2. **Case-insensitive suffix** — `template` →
       `[DashboardTemplate, MessageTemplate, HogFlowTemplate]`. Common when
       an action exposes a sub-resource under a parent's namespace.

    The caller emits one record per match so the runtime test fans out;
    if any one is unscoped, we surface the IDOR.
    """
    if not thing:
        return []
    pascal = "".join(seg.title() for seg in thing.split("_"))
    if pascal in _ALL_TENANT_SCOPED:
        return [pascal]
    pascal_lower = pascal.lower()
    return sorted(m for m in _ALL_TENANT_SCOPED if m.lower().endswith(pascal_lower))
