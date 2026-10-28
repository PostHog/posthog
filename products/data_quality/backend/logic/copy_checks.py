import re
from copy import deepcopy

from django.db import transaction

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.parser import parse_select
from posthog.hogql.resolver import resolve_types
from posthog.hogql.visitor import CloningVisitor

from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery

from ..facade.enums import SubjectStatus, SubjectType
from ..models import DataQualityCheck
from .compiler import compile_check, related_subject_ref
from .errors import CheckConfigError, SubjectUnresolvableError
from .serialization import compute_fingerprint
from .subjects import resolve_subject


class _InlineCheckSubject(CloningVisitor):
    def __init__(self, name: str, query: str) -> None:
        super().__init__(clear_types=True)
        self.name = name
        self.query = query

    def visit_join_expr(self, node: ast.JoinExpr) -> ast.JoinExpr:
        result = super().visit_join_expr(node)
        if isinstance(node.table, ast.Field) and node.table.chain == self.name.split("."):
            result.table = parse_select(self.query)
            result.alias = node.alias or self.name
        return result


def check_resolves(check: DataQualityCheck, database: Database | None = None) -> bool:
    try:
        related = related_subject_ref(check.check_type, check.config)
        compiled = compile_check(
            check_type=check.check_type,
            subject=resolve_subject(check.team_id, check.subject_type, str(check.subject_uuid)),
            column_name=check.column_name,
            config=check.config,
            related_subject=resolve_subject(check.team_id, *related) if related else None,
        )
        query = compiled.query
        if check.subject_type == SubjectType.VIEW:
            if check.saved_query_id is None:
                return False
            saved_query = DataWarehouseSavedQuery.objects.get(team_id=check.team_id, id=check.saved_query_id)
            saved_query_query = saved_query.query
            if not isinstance(saved_query_query, dict) or not isinstance(saved_query_query.get("query"), str):
                return False
            query = _InlineCheckSubject(saved_query.name, saved_query_query["query"]).visit(query)
        resolve_types(
            query,
            HogQLContext(
                team_id=check.team_id,
                enable_select_queries=True,
                bypass_warehouse_access_control=True,
                database=database or Database.create_for(team_id=check.team_id, bypass_warehouse_access_control=True),
            ),
            dialect="clickhouse",
        )
        return True
    except (ExposedHogQLError, CheckConfigError, SubjectUnresolvableError):
        return False


def _copy_name(name: str, source_name: str, target_name: str, collision_suffix: str = "") -> str:
    source_suffix = "__" + re.sub(r"[^A-Za-z0-9_]", "_", source_name)[-48:]
    base = re.sub(re.escape(source_suffix) + r"(?:_[0-9a-f]{12})?$", "", name)
    target_suffix = "__" + re.sub(r"[^A-Za-z0-9_]", "_", target_name)[-48:] + collision_suffix
    return base[: 128 - len(target_suffix)] + target_suffix


def copy_checks_to_saved_query(team_id: int, source_saved_query_id: str, target_saved_query_id: str) -> int:
    target = DataWarehouseSavedQuery.objects.filter(team_id=team_id).exclude(deleted=True).get(id=target_saved_query_id)
    source = DataWarehouseSavedQuery.objects.filter(team_id=team_id).exclude(deleted=True).get(id=source_saved_query_id)
    checks = list(DataQualityCheck.objects.for_team(team_id).filter(saved_query_id=source.id).exclude(deleted=True))
    if not checks:
        return 0
    database = Database.create_for(team_id=team_id, bypass_warehouse_access_control=True)
    copied = 0
    with transaction.atomic():
        DataWarehouseSavedQuery.objects.select_for_update().get(team_id=team_id, id=target.id)
        for original in checks:
            fingerprint = compute_fingerprint(
                subject_type=SubjectType.VIEW,
                subject_uuid=str(target.id),
                check_type=original.check_type,
                column_name=original.column_name,
                config=original.config,
            )
            if (
                DataQualityCheck.objects.for_team(team_id)
                .filter(saved_query=target, fingerprint=fingerprint)
                .exclude(deleted=True)
                .exists()
            ):
                continue
            check = DataQualityCheck(
                team_id=team_id,
                saved_query=target,
                subject_type=SubjectType.VIEW,
                subject_name=target.name,
                check_type=original.check_type,
                column_name=original.column_name,
                config=deepcopy(original.config),
                fingerprint=fingerprint,
                description=original.description,
                severity=original.severity,
                enabled=original.enabled,
                tags=deepcopy(original.tags),
                created_source=original.created_source,
                created_by_id=original.created_by_id,
                definition_author_id=original.definition_author_id,
                owner_id=original.owner_id,
                ai_model=original.ai_model,
                confidence=original.confidence,
                reasoning=original.reasoning,
            )
            # Names address checks across the project, so each snapshot needs its own handle.
            if original.name:
                check.name = _copy_name(original.name, source.name, target.name)
                if DataQualityCheck.objects.for_team(team_id).filter(name=check.name).exclude(deleted=True).exists():
                    suffix = f"_{check.id.hex[-12:]}"
                    check.name = _copy_name(original.name, source.name, target.name, suffix)
            check.subject_status = (
                SubjectStatus.ACTIVE if check_resolves(check, database) else SubjectStatus.NEEDS_REVIEW
            )
            check.save()
            copied += 1
    return copied
