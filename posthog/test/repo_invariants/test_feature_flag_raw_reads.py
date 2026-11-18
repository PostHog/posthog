import re
import ast
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

import pytest

from test_feature_flag_gated_writes import (
    FLAG_NAME,
    REPO_ROOT,
    SCANNED_ROOTS,
    SCOPE_NODES,
    SKIPPED_PARTS,
    _chain_root,
    _imported_aliases,
    _is_flag,
    _own_nodes,
    _scope_flag_names,
    _terminal_name,
)

BASELINE = Path(__file__).with_name("feature_flag_raw_reads_baseline.txt")

DOCUMENT_METHODS = {"get", "items", "keys", "values", "setdefault", "pop", "update"}
FACADE_MODULE = "products.feature_flags.backend.facade"
FLAG_TABLE = re.compile(r"\bposthog_featureflag\b")
SQL_DOCUMENT_READ = re.compile(r"\bfilters\s*(->|#>|@>|<@|\?)|jsonb\w*\(\s*(\w+\.)?filters\b")

# The seam whose job is to read the stored document. A key is a file, or a file and a scope in it.
SEAM_REASONS: dict[str, str] = {
    "products/feature_flags/backend/facade/config.py": "format detection and the v2 structural reads",
    "products/feature_flags/backend/facade/config_validation.py": "the strict validator",
    "products/feature_flags/backend/facade/config_writes.py": "v2 writer admission",
    "products/feature_flags/backend/facade/references.py": "cohort and flag references, closed to other formats",
    "products/feature_flags/backend/facade/filters.py": "v1 transforms, closed to other formats",
    "products/feature_flags/backend/facade/rules.py": "the experiment-rule view, behind a format check",
    "products/feature_flags/backend/models/feature_flag.py::FeatureFlag._v1_filters": (
        "the single read behind the model's guarded accessors"
    ),
}

REGENERATE = (
    "Regenerate it with: python -c \"import sys; sys.path.insert(0, 'posthog/test/repo_invariants'); "
    'import test_feature_flag_raw_reads as t; t.write_baseline()"'
)


def _uses_model(tree: ast.AST) -> bool:
    return any(
        (isinstance(node, ast.ImportFrom) and any(alias.name == "FeatureFlag" for alias in node.names))
        or (isinstance(node, ast.ClassDef) and node.name == "FeatureFlag")
        for node in ast.walk(tree)
    )


def _class_flag_names(scope: ast.AST) -> set[str]:
    if not isinstance(scope, ast.ClassDef):
        return set()
    if scope.name == "FeatureFlag":
        return {"self"}
    # A flag serializer or viewset holds the flag it works on as `instance`.
    return {"instance", "self.instance"} if FLAG_NAME.search(scope.name) else set()


def _call_label(call: ast.Call) -> str:
    first = call.args[0] if call.args else None
    argument = repr(first.value) if isinstance(first, ast.Constant) else ("..." if call.args else "")
    return f"{ast.unparse(call.func)}({argument})"


class _Reader:
    def __init__(self, tree: ast.AST) -> None:
        self.parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
        self.models = _imported_aliases(tree, "FeatureFlag")
        self.uses_model = _uses_model(tree)
        self.facade = {
            alias.asname or alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(FACADE_MODULE)
            for alias in node.names
        }
        self.seen_strings: set[ast.AST] = set()

    def _is_document(self, node: ast.AST, flag_names: set[str]) -> bool:
        if isinstance(node, ast.Attribute) and node.attr == "filters":
            owner = node.value
        elif isinstance(node, ast.Subscript) and _is_filters_key(node.slice):
            owner = node.value
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get":
            if not (node.args and _is_filters_key(node.args[0])):
                return False
            owner = node.func.value
        else:
            return False
        return _is_flag(owner, flag_names) or ast.unparse(owner) in flag_names

    def _on_flag_queryset(self, call: ast.Call, flag_names: set[str]) -> bool:
        node: ast.AST | None = call
        # A Q(...) has no receiver: judge the queryset method it is passed to.
        while node is not None and not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            node = self.parents.get(node)
        if not isinstance(node, ast.Call):
            return self.uses_model
        root = _chain_root(node.func)
        if not isinstance(root, ast.Name):
            return self.uses_model
        if root.id in self.models or root.id in flag_names or FLAG_NAME.search(root.id):
            return True
        # Another model's manager, such as Cohort.objects.
        return self.uses_model and not root.id[:1].isupper()

    def _document_read(self, expr: ast.AST, *, follow_alias: bool = True) -> str | None:
        parent = self.parents.get(expr)
        if isinstance(parent, ast.BoolOp) and isinstance(parent.op, ast.Or) and parent.values[0] is expr:
            expr, parent = parent, self.parents.get(parent)
        text = ast.unparse(expr)
        if isinstance(parent, ast.Subscript) and parent.value is expr:
            return ast.unparse(parent)
        if isinstance(parent, ast.Attribute) and parent.attr in DOCUMENT_METHODS:
            call = self.parents.get(parent)
            if isinstance(call, ast.Call) and call.func is parent:
                return _call_label(call)
        if isinstance(parent, (ast.For, ast.AsyncFor, ast.comprehension)) and parent.iter is expr:
            return f"for in {text}"
        if isinstance(parent, ast.Compare) and expr in parent.comparators:
            if any(isinstance(op, (ast.In, ast.NotIn)) for op in parent.ops):
                return f"in {text}"
        if isinstance(parent, ast.Dict) and any(k is None and v is expr for k, v in zip(parent.keys, parent.values)):
            return f"**{text}"
        if follow_alias and isinstance(parent, (ast.Assign, ast.AnnAssign)) and parent.value is expr:
            targets: list[ast.expr] = parent.targets if isinstance(parent, ast.Assign) else [parent.target]
            if all(isinstance(target, ast.Name) for target in targets) and self._alias_is_read(parent, targets):
                return f"{ast.unparse(targets[0])} = {text}"
        return None

    def _alias_is_read(self, assignment: ast.AST, targets: list[ast.expr]) -> bool:
        """Whether a name bound to the document is read into later. The binding is where the read is counted."""
        scope: ast.AST | None = assignment
        while scope is not None and not isinstance(scope, (*SCOPE_NODES, ast.Module)):
            scope = self.parents.get(scope)
        names = {target.id for target in targets if isinstance(target, ast.Name)}
        return scope is not None and any(
            isinstance(node, ast.Name)
            and node.id in names
            and isinstance(node.ctx, ast.Load)
            and self._document_read(node, follow_alias=False) is not None
            for node in _own_nodes(scope)
        )

    def _get_filters_read(self, call: ast.Call) -> str | None:
        func = call.func
        if not (isinstance(func, ast.Attribute) and func.attr == "get_filters") or call.args or call.keywords:
            return None
        parent = self.parents.get(call)
        if isinstance(parent, ast.Call) and call in parent.args and _terminal_name(parent.func) in self.facade:
            # Handed straight to a facade function, which checks the format itself.
            return None
        return ast.unparse(call)

    def _query_reads(self, call: ast.Call, flag_names: set[str]) -> Iterator[str]:
        name = _terminal_name(call.func)
        lookups = [kw.arg for kw in call.keywords if kw.arg and kw.arg.startswith("filters__")]
        if lookups and self._on_flag_queryset(call, flag_names):
            yield from (f"{name}({lookup})" for lookup in lookups)
        if name == "KeyTransform" and self.uses_model and call.args:
            last = call.args[-1]
            if isinstance(last, ast.Constant) and last.value == "filters":
                yield ast.unparse(call)
        if name == "extra" and self._on_flag_queryset(call, flag_names):
            strings = [sub for sub in ast.walk(call) if isinstance(sub, (ast.Constant, ast.JoinedStr))]
            if any(SQL_DOCUMENT_READ.search(_text(sub)) for sub in strings):
                self.seen_strings.update(strings)
                yield "extra(sql on filters)"

    def _sql_read(self, node: ast.Constant | ast.JoinedStr) -> str | None:
        if node in self.seen_strings or isinstance(self.parents.get(node), (ast.JoinedStr, ast.Expr)):
            return None
        text = _text(node)
        if FLAG_TABLE.search(text) and SQL_DOCUMENT_READ.search(text):
            return "sql on posthog_featureflag.filters"
        return None

    def reads(self, node: ast.AST, flag_names: set[str]) -> Iterator[str]:
        if self._is_document(node, flag_names):
            read = self._document_read(node)
        elif isinstance(node, ast.Call):
            yield from self._query_reads(node, flag_names)
            read = self._get_filters_read(node)
        elif isinstance(node, (ast.Constant, ast.JoinedStr)):
            read = self._sql_read(node)
        else:
            read = None
        if read is not None:
            yield read


def _is_filters_key(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value == "filters"


def _text(node: ast.AST) -> str:
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else ""
    if isinstance(node, ast.JoinedStr):
        return "".join(_text(part) for part in node.values)
    return ""


def raw_reads(tree: ast.AST, *, path: str = "") -> list[str]:
    reader = _Reader(tree)
    found: list[str] = []

    def visit(scope: ast.AST, label: str, inherited: set[str]) -> None:
        if f"{path}::{label}" in SEAM_REASONS:
            return
        flag_names = inherited | _scope_flag_names(scope, reader.models) | _class_flag_names(scope)
        for node in _own_nodes(scope):
            found.extend(f"{label or '<module>'}::{read}" for read in reader.reads(node, flag_names))
            if isinstance(node, SCOPE_NODES):
                name = getattr(node, "name", "<lambda>")
                visit(node, f"{label}.{name}" if label else name, flag_names)

    visit(tree, "", set())
    return found


def _scan() -> Counter[str]:
    found: Counter[str] = Counter()
    for root in SCANNED_ROOTS:
        for path in (REPO_ROOT / root).rglob("*.py"):
            relative = path.relative_to(REPO_ROOT)
            if (
                SKIPPED_PARTS & set(relative.parts)
                or relative.name.startswith("test_")
                or relative.name == "conftest.py"
            ):
                continue
            key = relative.as_posix()
            if key in SEAM_REASONS:
                continue
            source = path.read_text(errors="ignore")
            if "filters" not in source:
                continue
            if "FeatureFlag" not in source and not FLAG_NAME.search(source):
                continue
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue
            for read in raw_reads(tree, path=key):
                found[f"{key}::{read}"] += 1
    return found


def _read_baseline() -> Counter[str]:
    lines = BASELINE.read_text().splitlines() if BASELINE.exists() else []
    return Counter(line for line in lines if line and not line.startswith("#"))


def write_baseline() -> None:
    header = "# Generated by write_baseline() in test_feature_flag_raw_reads.py. Shrink it, never grow it.\n"
    BASELINE.write_text(header + "".join(f"{entry}\n" for entry in sorted(_scan().elements())))


def test_feature_flag_filters_are_read_through_the_seam() -> None:
    # A v1 key read on a document in another config format answers as a v1 flag with no conditions.
    found = _scan()
    baseline = _read_baseline()

    new = sorted((found - baseline).elements())
    assert not new, (
        f"New raw reads of FeatureFlag.filters: {new}. Read through the model accessors "
        "(flag.conditions, flag.variants, flag.get_payload(...)) or a function in "
        "products/feature_flags/backend/facade/, which check the config format first."
    )

    removed = sorted((baseline - found).elements())
    assert not removed, f"The baseline lists raw reads that no longer exist: {removed}. {REGENERATE}"


@pytest.mark.parametrize(
    "snippet,expected",
    [
        ("flag.filters['groups']", 1),
        ("flag.filters['multivariate']['variants']", 1),
        ("flag.filters.get('groups', [])", 1),
        ("flag.filters['payloads'] = {}", 1),
        ("(flag.filters or {}).get('groups')", 1),
        ("(survey.targeting_flag.filters or {})['groups']", 1),
        ("filters = flag.filters or {}\nfilters.get('groups')", 1),
        ("filters = flag.filters\nfor group in filters['groups']:\n    pass", 1),
        ("(flag_data.get('filters') or {}).get('payloads')", 1),
        ("serialized_flag['filters']['payloads'] = {}", 1),
        ("filters = feature_flag_data.get('filters')\n'payloads' in filters", 1),
        ("for key in feature_flag.filters:\n    pass", 1),
        ("'groups' in flag.filters", 1),
        ("{**existing_flag.filters, 'groups': []}", 1),
        ("flag.get_filters()", 1),
        ("flag.get_filters()['groups']", 1),
        ("row.get_filters().get('payloads')", 1),
        ("def f(row: FeatureFlag):\n    row.filters.get('groups')", 1),
        ("for row in FeatureFlag.objects.all():\n    row.filters['groups']", 1),
        ("class FeatureFlag:\n    def f(self):\n        return self.filters['groups']", 1),
        ("class FeatureFlagSerializer:\n    def f(self):\n        return self.instance.filters.get('groups')", 1),
        ("FeatureFlag.objects.filter(filters__groups__0__properties__isnull=False)", 1),
        ("from m import FeatureFlag\nqueryset.filter(Q(filters__multivariate__variants=[]))", 1),
        ("FeatureFlag.objects.filter(team=team).extra(where=[\"jsonb_path_exists(filters, '$')\"])", 1),
        ("from m import FeatureFlag\nKeyTransform('variants', KeyTransform('multivariate', 'filters'))", 1),
        ("SQL = \"SELECT 1 FROM posthog_featureflag WHERE posthog_featureflag.filters->'groups' IS NULL\"", 1),
        ("WHERE = f\"posthog_featureflag.filters->'{key}' IS NULL OR posthog_featureflag.filters IS NULL\"", 1),
        (
            "from products.feature_flags.backend.facade.filters import set_feature_enrollment\n"
            "set_feature_enrollment(flag.get_filters(), True)",
            0,
        ),
        ("payload = {'filters': flag.filters}", 0),
        ("filters = flag_data.get('filters', {})\nflag_dependency_properties(filters)", 0),
        ("flag_dependency_properties(flag['filters'])", 0),
        ("validated_data['filters']['groups']", 0),
        ("flag.filters = {}", 0),
        ("copy.deepcopy(flag.filters)", 0),
        ("cohort.filters.get('properties')", 0),
        ("(dashboard.filters or {}).get('date_from')", 0),
        ("class CohortSerializer:\n    def f(self):\n        return self.instance.filters.get('properties')", 0),
        ("serializer.get_filters(dashboard)['date_from']", 0),
        ("Cohort.objects.filter(filters__properties__isnull=False)", 0),
        ("from m import FeatureFlag\nCohort.objects.filter(Q(filters__properties={}))", 0),
        ("queryset.filter(Q(filters__properties={}))", 0),
        ("from m import FeatureFlag\nCohort.objects.filter(pk=1).extra(where=[\"filters ? 'x'\"])", 0),
        ("SQL = \"SELECT filters->'groups' FROM posthog_cohort\"", 0),
        ("SQL = 'SELECT id, filters FROM posthog_featureflag'", 0),
        ('def f():\n    """Reads posthog_featureflag.filters->\'groups\'."""', 0),
    ],
)
def test_scanner_detects_raw_reads(snippet: str, expected: int) -> None:
    assert len(raw_reads(ast.parse(snippet))) == expected


def test_seam_scopes_are_exempt() -> None:
    tree = ast.parse(
        "class FeatureFlag:\n"
        "    def _v1_filters(self):\n        return self.get_filters()\n"
        "    def other(self):\n        return self.get_filters()"
    )
    path = "products/feature_flags/backend/models/feature_flag.py"
    assert raw_reads(tree, path=path) == ["FeatureFlag.other::self.get_filters()"]
