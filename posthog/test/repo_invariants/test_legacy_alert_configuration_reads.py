import re
import ast
from collections.abc import Iterator
from pathlib import Path

import pytest

from repo_invariant_scan_scope import ScanScope

REPO_ROOT = Path(__file__).resolve().parents[3]
SCANNED_ROOTS = ("common", "ee", "posthog", "products")
SKIPPED_PARTS = {"test", "tests", "migrations", "__snapshots__"}

LEGACY_MODELS = {"AlertConfiguration", "LogsAlertConfiguration"}
MANAGERS = {"objects", "_default_manager", "_base_manager"}
TYPE_ONLY_CALLS = {"isinstance", "issubclass", "cast"}
# Reverse accessors and the foreign key from AlertCheck, AlertSubscription and investigations.
RELATED_ATTRIBUTES = {"alertconfiguration_set", "alert_configurations", "alert_configuration"}
LOOKUP = re.compile(r"(?:^|__)(?:alert_configurations?__|alertconfiguration__|alertconfiguration_set(?:__|$))")
LEGACY_STRING = re.compile(
    r"\b(posthog_alertconfiguration|logs_logsalertconfiguration)\b"
    r"|^(alerts\.AlertConfiguration|logs\.LogsAlertConfiguration)$"
)
# LogsAlertCheck.alert and LogsAlertEvent.alert point at the logs row. `alert` is too common a name to
# match everywhere, so it counts only in a file that uses one of these models.
LOGS_ROW_CHILDREN = ("LogsAlertCheck", "LogsAlertEvent")
APP_MODEL_LABELS = {("alerts", "AlertConfiguration"), ("logs", "LogsAlertConfiguration")}
LOGS_ROW_LOOKUP = re.compile(r"(?:^|__)alert(?:__|$)")
SOURCE_MARKERS = ("AlertConfiguration", "alert_configuration", "alertconfiguration", *LOGS_ROW_CHILDREN)
SCOPE_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)

# Code that may read a legacy insight or logs alert row. A key is a file, or a file and a scope in it
# ("Class", "Class.method", "function"); a scope key also covers the scopes nested in it.
# A reason names the step of the legacy alert retirement that removes the read:
# A6-A8 plan limits count platform alerts, B1-B6 reads use the platform copy, D1-D4 checks and delivery
# build from the copy, E1-E5 creates and edits stop writing rows, G1-G3 history moves and rows and
# models are deleted, H3 subscribers move to platform destination rows.
READERS: dict[str, str] = {
    "products/alerts/backend/models/alert.py": "the AlertConfiguration model and its subscription and check rows (G3)",
    "products/logs/backend/models.py": "the LogsAlertConfiguration model and its check and event rows (G3)",
    "products/alerts/backend/models/investigation.py": "investigation rows keep a foreign key to the row (G3)",
    "products/pulse/backend/models.py": "Pulse links keep a foreign key to the row (G3)",
    "products/alerts/backend/admin.py": "Django admin for the model (G3)",
    "products/alerts/backend/platform_ownership.py": "create hand-over, row locks; moved edits write the copy (E1)",
    "products/logs/backend/platform_ownership.py": "ownership layer: create (E1)",
    "products/logs/backend/facade/platform_ownership.py": "ownership facade for the logs API's creates (E1)",
    "products/alerts/backend/platform_cutover.py": "hands a new alert to the platform (E1)",
    "products/logs/backend/destination_conversion.py": "moves destinations off HogFunctions under the row's lock (H5)",
    "products/alerts/backend/platform_alert_backfill.py": "builds copies from rows",
    "products/logs/backend/platform_alert_backfill.py": "builds copies from rows",
    "products/alerts/backend/management/commands/backfill_platform_insight_alert_created_at.py": "backfill from rows",
    "products/alerts/backend/management/commands/backfill_platform_insight_alert_creators.py": "backfill from rows",
    "products/logs/backend/management/commands/backfill_platform_logs_alert_created_at.py": "backfill from rows",
    "products/logs/backend/management/commands/backfill_platform_logs_alert_creators.py": "backfill from rows",
    "products/alerts/backend/management/commands/delete_orphaned_platform_insight_alert_copies.py": (
        "finds copies whose row is gone"
    ),
    "products/logs/backend/management/commands/delete_orphaned_platform_logs_alert_copies.py": (
        "finds copies whose row is gone"
    ),
    "products/alerts/backend/legacy_row_switch_off.py": "F1 switches off legacy rows",
    "products/logs/backend/legacy_row_switch_off.py": "F1 switches off legacy rows",
    "products/alerts/backend/legacy_history_copy.py": "G1 history copy",
    "products/logs/backend/legacy_history_copy.py": "G1 history copy",
    "products/alerts/backend/platform_native_cleanup.py": "tells native alerts from copies by row existence (E2)",
    "products/alerts/backend/alert_comparison.py": "shadow comparison of row and copy checks (D4)",
    "products/logs/backend/alert_comparison.py": "shadow comparison of row and copy checks (D4)",
    "products/alerts/backend/platform_insight_alert.py": (
        "loads a row by id and puts its copy's settings on it, for investigations and firing signals (G3)"
    ),
    "products/logs/backend/alert_source_cycle.py": (
        "`_as_configured_now` refreshes a copy the logs stack owns from its row (E2)"
    ),
    "products/logs/backend/facade/api.py::_close_if_subscribed": "incident close reads `owner` from the row (E4)",
    "products/alerts/backend/platform_hooks.py": "viewer by the row's insight; creator from the copy (G2)",
    "products/logs/backend/platform_hooks.py": "creator and viewer of an alert with a row, else of the copy (G2)",
    "products/alerts/backend/evaluation/detector.py": "earlier AI flags by row id and handover time only (G3)",
    "posthog/temporal/ai/anomaly_investigation/workflow.py::_investigated_alert": (
        "investigation loads the row with its copy's settings (G3)"
    ),
    "products/alerts/backend/platform_investigation.py": "investigation's row, with its copy's settings (G3)",
    "products/alerts/backend/activity_logging.py": "activity log of row edits (G2)",
    "products/logs/backend/activity_logging.py": "activity log of row edits (G2)",
    # The legacy evaluators, which stop when the source stacks shut down.
    "posthog/temporal/alerts/activities.py": "legacy insight evaluator",
    "posthog/tasks/alerts/investigation_notifications.py": "legacy insight evaluator's investigation safety net",
    "posthog/tasks/alerts/utils.py::dispatch_alert_notification": "legacy delivery skips platform-owned rows (D2)",
    "posthog/tasks/alerts/utils.py::_thresholds_drawn_on_chart": (
        "firing chart draws the rows the insight stack owns; moved alerts draw from their copies (G3)"
    ),
    "products/logs/backend/temporal/activities.py": "legacy logs evaluator",
    "products/logs/backend/alert_creation.py": "alert limit counts rows (A6-A8)",
    "products/alerts/backend/llm_detector_limits.py": "AI cap counts insight-owned rows, then copies (G3)",
    "products/logs/backend/alert_deletion.py": "deletes the row with its copy (G2)",
    "products/logs/backend/native_alerts.py": "validates a native alert as an unsaved row and saves nothing (G3)",
    "products/alerts/backend/max_tools.py::UpsertAlertTool": "Max create writes the row; edits write the copy (E1)",
    "products/alerts/backend/presentation/views/alert.py::AlertSerializer": (
        "insight API create writes the row (E1); moved edits write the copy"
    ),
    "products/logs/backend/presentation/views/alerts_api.py::LogsAlertConfigurationSerializer": (
        "logs alert API serializes and writes the row (E1, E2)"
    ),
    "products/logs/backend/presentation/views/alerts_api.py::LogsAlertViewSet.simulate": (
        "simulation builds an unsaved row and saves nothing (G3)"
    ),
    "products/alerts/backend/platform_subscribers.py": "subscriber rows point at the row (H3)",
    "products/alerts/backend/tasks/tasks.py": "removes a departed member's subscriptions (H3)",
    "products/alerts/backend/facade/api.py::insight_short_ids_watched_by": (
        "subscriptions on the row; a moved alert's on/off and creator from its copy (H3)"
    ),
    "products/alerts/backend/facade/api.py::snooze_alert_from_slack": (
        "locks the row; a moved alert's on/off and snooze live on its copy (G3)"
    ),
    "products/alerts/backend/logic/ownership.py::_load_alert": (
        "loads the row with its copy's settings, or the native alert (G3)"
    ),
    "products/alerts/backend/logic/ownership.py::take_alert_ownership": (
        "ownership keeps an unsaved pre-write state for limit checks (G3)"
    ),
    "products/alerts/backend/logic/alert_validation.py::validate_alert_write": (
        "shared write validation builds an unsaved row for limit checks (G3)"
    ),
    "products/alerts/backend/facade/api.py::delete_insight_alerts": "deletes rows with their insight (G2)",
    # Read surfaces: rows the source stack still owns; platform-owned alerts read their copy (B1-B5).
    "products/alerts/backend/presentation/views/alert.py::AlertViewSet": "rows shown with their copy's settings (B2)",
    "products/logs/backend/presentation/views/alerts_api.py::LogsAlertViewSet": "logs alert API (B1)",
    "products/alerts/backend/facade/api.py::_insight_owned_rows": "rows the insight stack owns (B3)",
    "products/alerts/backend/facade/api.py::insight_ids_with_alerts": "insights with a row or a native alert (B3)",
    "products/alerts/backend/facade/api.py::get_alert_team_id": "team of an alert with a row (G2)",
    "products/alerts/backend/presentation/views/insight_alerts.py": "embeds rows with their copy's settings (B3)",
    "products/dashboards/backend/presentation/views/dashboard.py::tile_insight_prefetches": (
        "dashboard tiles prefetch rows, shown with their copy's settings (B3)"
    ),
    "posthog/hogql/database/schema/system.py::<module>": "`system.alerts` and `system.logs_alerts` (B1, B3)",
    "products/alerts/backend/alert_search.py": "Max entity search (B3)",
    "products/alerts/backend/logic/alert_email.py": "recipients from the row's insight and subscriptions (H3)",
    "products/logs/backend/destination_buckets.py": "report that informs a cutover",
    "products/logs/backend/delivery_path_report.py": "report that informs a cutover",
    "products/alerts/backend/presentation/views/alert.py::ThresholdViewSet": "thresholds endpoint (B6)",
    "products/alerts/backend/presentation/views/alert.py::ThresholdWithAlertSerializer": "thresholds endpoint (B6)",
    "products/alerts/backend/presentation/views/alert.py::_ThresholdsSerializer": "thresholds endpoint (B6)",
}


class _Reader:
    def __init__(self, tree: ast.AST) -> None:
        self.parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
        self.annotations = {id(node) for annotation in _annotations(tree) for node in ast.walk(annotation)}
        self.models = LEGACY_MODELS | {
            alias.asname
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
            if alias.name in LEGACY_MODELS and alias.asname
        }
        self.uses_logs_row_children = any(
            isinstance(node, ast.Name) and node.id in LOGS_ROW_CHILDREN for node in ast.walk(tree)
        ) or any(
            isinstance(node, ast.ImportFrom) and any(alias.name in LOGS_ROW_CHILDREN for alias in node.names)
            for node in ast.walk(tree)
        )

    def is_read(self, node: ast.AST) -> bool:
        if id(node) in self.annotations:
            return False
        parent = self.parents.get(node)
        if isinstance(node, ast.Name) and node.id in self.models:
            return self._model_is_read(node, parent)
        if isinstance(node, ast.Attribute) and node.attr in LEGACY_MODELS:
            return self._model_is_read(node, parent)
        if isinstance(node, ast.Attribute) and node.attr in RELATED_ATTRIBUTES:
            return True
        if isinstance(node, ast.Attribute) and node.attr == "alert":
            return self.uses_logs_row_children and isinstance(node.ctx, ast.Load)
        if isinstance(node, ast.Call) and _called_name(node) == "get_model":
            labels = tuple(arg.value for arg in node.args if isinstance(arg, ast.Constant))
            return labels in APP_MODEL_LABELS
        if isinstance(node, ast.keyword) and node.arg is not None:
            if self.uses_logs_row_children and node.arg.startswith("alert__"):
                return True
            return bool(LOOKUP.search(node.arg))
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if isinstance(parent, ast.Expr):
                return False
            # `order_by` marks a descending field with a leading `-`, which is not part of the lookup.
            field = node.value.removeprefix("-")
            if field in {"alert_configuration", "alert_configurations"}:
                return self._names_a_relation(parent)
            if self.uses_logs_row_children and LOGS_ROW_LOOKUP.search(field):
                # A lookup through `alert` joins the logs row in any query call, not only the relation loaders.
                if field != "alert":
                    return isinstance(parent, ast.Call)
                return self._names_a_relation(parent)
            return bool(LEGACY_STRING.search(node.value) or LOOKUP.search(field))
        return False

    def _model_is_read(self, node: ast.AST, parent: ast.AST | None) -> bool:
        if isinstance(parent, ast.Attribute) and parent.value is node:
            return parent.attr in MANAGERS
        if isinstance(parent, ast.Call) and node in parent.args:
            return _called_name(parent) not in TYPE_ONLY_CALLS
        if isinstance(parent, ast.Tuple) and isinstance(self.parents.get(parent), ast.Call):
            call = self.parents[parent]
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id in TYPE_ONLY_CALLS:
                return False
        return True

    def _names_a_relation(self, parent: ast.AST | None) -> bool:
        if not isinstance(parent, ast.Call):
            return False
        return _called_name(parent) in {
            "select_related",
            "prefetch_related",
            "Prefetch",
            "only",
            "values",
            "values_list",
            "order_by",
        }


def _called_name(call: ast.Call) -> str:
    func = call.func
    return func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""


def _annotations(tree: ast.AST) -> Iterator[ast.AST]:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            arguments = node.args
            every = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs, arguments.vararg, arguments.kwarg]
            yield from (argument.annotation for argument in every if argument and argument.annotation)
            if node.returns:
                yield node.returns
        elif isinstance(node, ast.AnnAssign):
            yield node.annotation


def legacy_reads(tree: ast.AST) -> list[str]:
    reader = _Reader(tree)
    found: list[str] = []

    def visit(scope: ast.AST, label: str) -> None:
        for node in _own_descendants(scope):
            if isinstance(node, SCOPE_NODES):
                visit(node, f"{label}.{node.name}" if label else node.name)
            elif reader.is_read(node):
                found.append(label or "<module>")

    visit(tree, "")
    return found


def _own_descendants(node: ast.AST) -> Iterator[ast.AST]:
    # A nested function or class is yielded, so the caller can give it its own label, but not entered.
    for child in ast.iter_child_nodes(node):
        yield child
        if not isinstance(child, SCOPE_NODES):
            yield from _own_descendants(child)


def _scan(scope: ScanScope) -> set[str]:
    found: set[str] = set()
    roots = [REPO_ROOT / root for root in SCANNED_ROOTS]
    for _, path in scope.walk(REPO_ROOT, roots, "*.py"):
        relative = path.relative_to(REPO_ROOT)
        if SKIPPED_PARTS & set(relative.parts) or relative.name.startswith("test_") or relative.name == "conftest.py":
            continue
        source = path.read_text(errors="ignore")
        if not any(marker in source for marker in SOURCE_MARKERS):
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        found.update(f"{relative.as_posix()}::{label}" for label in legacy_reads(tree))
    return found


def _allowing_key(read: str) -> str | None:
    path, label = read.split("::", 1)
    if path in READERS:
        return path
    parts = label.split(".")
    for end in range(len(parts), 0, -1):
        key = f"{path}::{'.'.join(parts[:end])}"
        if key in READERS:
            return key
    return None


def test_legacy_alert_configurations_are_read_only_by_listed_code() -> None:
    scope = ScanScope.from_environment()
    found = _scan(scope)

    new = sorted(read for read in found if _allowing_key(read) is None)
    assert not new, (
        "New reads of a legacy alert row (AlertConfiguration or LogsAlertConfiguration):\n"
        + "\n".join(f"  {read}" for read in new)
        + "\nLegacy rows are disabled and then deleted once every alert is on the alerts platform, so this read "
        "would break then. Read the alert from PlatformAlertConfiguration instead, through "
        "products/alerts_platform/backend/facade. If the read belongs to the ownership, cutover or rollback "
        "code, or a later retirement step removes it, add the file or scope to READERS in this test with a "
        "one-line reason or the step that removes it."
    )

    used = {_allowing_key(read) for read in found}
    stale = sorted(key for key in READERS if key not in used and scope.covers(key.split("::", 1)[0]))
    assert not stale, (
        f"READERS lists code that no longer reads a legacy alert row: {stale}. Remove those entries from this test."
    )


@pytest.mark.parametrize(
    "snippet,expected",
    [
        ("AlertConfiguration.objects.filter(team_id=1)", ["<module>"]),
        ("def f():\n    return LogsAlertConfiguration.objects.get(id=1)", ["f"]),
        ("class V:\n    def list(self):\n        AlertConfiguration._base_manager.all()", ["V.list"]),
        ("models.AlertConfiguration.objects.all()", ["<module>"]),
        ("Prefetch('alertconfiguration_set', queryset=qs)", ["<module>"]),
        ("insight.alertconfiguration_set.all()", ["<module>"]),
        ("AlertCheck.objects.filter(alert_configuration__team_id=1)", ["<module>"]),
        ("AlertCheck.objects.select_related('alert_configuration')", ["<module>"]),
        ("check.alert_configuration.name", ["<module>"]),
        ("if enabled:\n    def f():\n        return AlertConfiguration.objects.all()", ["f"]),
        (
            "try:\n    class C:\n        def m(self):\n            AlertConfiguration.objects.all()\nexcept E:\n    pass",
            ["C.m"],
        ),
        ("from m import AlertConfiguration as LegacyAlert\nLegacyAlert.objects.all()", ["<module>"]),
        ("User.objects.prefetch_related('alert_configurations')", ["<module>"]),
        ("User.objects.filter(alert_configurations__enabled=True)", ["<module>"]),
        ("LogsAlertEvent.objects.select_related('alert').first().alert.name", ["<module>", "<module>"]),
        ("from m import LogsAlertCheck\nchecks.filter(alert__team_id=1)", ["<module>"]),
        ("result.alert.name", []),
        ("from m import LogsAlertEvent\nLogsAlertEvent.objects.order_by('alert__name')", ["<module>"]),
        ("from m import LogsAlertCheck\nchecks.annotate(name=F('alert__name'))", ["<module>"]),
        ("AlertCheck.objects.order_by('alert_configuration')", ["<module>"]),
        ("from m import LogsAlertCheck\nchecks.order_by('-created_at')", []),
        ("from m import LogsAlertEvent\nLogsAlertEvent.objects.order_by('-alert__name')", ["<module>"]),
        ("AlertCheck.objects.order_by('-alert_configuration__name')", ["<module>"]),
        ("apps.get_model('alerts', 'AlertConfiguration').objects.all()", ["<module>"]),
        ("apps.get_model('logs', 'LogsAlertConfiguration')", ["<module>"]),
        ("apps.get_model('alerts', 'AlertCheck')", []),
        ("Prefetch('alert')", []),
        ("Prefetch('insight__alertconfiguration_set')", ["<module>"]),
        ("class S:\n    class Meta:\n        model = AlertConfiguration", ["S.Meta"]),
        ("LogsAlertConfiguration(team_id=1, name='x')", ["<module>"]),
        ("SQL = 'SELECT id FROM posthog_alertconfiguration'", ["<module>"]),
        ("Table(postgres_table_name='logs_logsalertconfiguration')", ["<module>"]),
        ("ForeignKey('alerts.AlertConfiguration', on_delete=CASCADE)", ["<module>"]),
        ("def f(alert: AlertConfiguration) -> AlertConfiguration | None:\n    return alert", []),
        ("alert: LogsAlertConfiguration = build()", []),
        ("from products.alerts.backend.models.alert import AlertConfiguration", []),
        ("isinstance(alert, AlertConfiguration)", []),
        ("isinstance(alert, (AlertConfiguration, LogsAlertConfiguration))", []),
        ("LogsAlertConfiguration.State.SNOOZED", []),
        ("try:\n    pass\nexcept AlertConfiguration.DoesNotExist:\n    pass", []),
        ("AlertConfiguration.from_platform_view(view, team_id=1)", []),
        ("PlatformAlertConfiguration.objects.all()", []),
        ("alert_configuration_id = check.alert_configuration_id", []),
        ("payload = {'alert_configuration': 1}", []),
        ('def f():\n    """Reads posthog_alertconfiguration rows."""', []),
    ],
)
def test_scanner_finds_legacy_reads(snippet: str, expected: list[str]) -> None:
    assert legacy_reads(ast.parse(snippet)) == expected
