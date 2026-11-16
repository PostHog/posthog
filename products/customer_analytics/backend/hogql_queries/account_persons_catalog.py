from collections.abc import Callable, Iterator
from contextlib import contextmanager
from time import perf_counter
from typing import TYPE_CHECKING

from posthog.schema import ActorsQuery, PersonPropertyFilter, PropertyGroupFilterValue

from posthog.hogql import ast
from posthog.hogql.database.database import Database
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.parser import parse_expr, parse_order_expr

from posthog.models import Team, User
from posthog.ph_client import get_feature_flag_or_none
from posthog.slo.events import emit_slo_completed, emit_slo_started
from posthog.slo.types import SloArea, SloCompletedProperties, SloOperation, SloOutcome, SloStartedProperties

if TYPE_CHECKING:
    from posthog.schema import HogQLQueryModifiers

    from posthog.hogql.timings import HogQLTimings

    from products.access_control.backend.facade.user_access_control import UserAccessControl


ACCOUNT_PERSONS_CATALOG_FLAG = "account-persons-builtin-catalog"
PERSON_COLUMNS = frozenset({"id", "created_at", "last_seen_at", "is_identified", "team_id"})
MEMBERSHIP_COLUMNS = frozenset({"person_id", "distinct_ids", "account_first_seen", "account_last_seen"})


class AccountPersonsCatalog:
    @staticmethod
    def supports_expression(expression: ast.Expr) -> bool:
        if isinstance(expression, ast.Alias):
            return AccountPersonsCatalog.supports_expression(expression.expr)
        if isinstance(expression, ast.Field):
            chain = expression.chain
            if len(chain) == 2 and chain[0] == "source":
                return chain[1] in MEMBERSHIP_COLUMNS
            if chain and chain[0] == "persons":
                chain = chain[1:]
            if len(chain) == 1:
                return chain[0] in PERSON_COLUMNS or chain[0] == "properties"
            if len(chain) == 2 and chain[0] == "properties":
                return isinstance(chain[1], str) and not chain[1].startswith("$virt_")
            return False
        if isinstance(expression, ast.Constant):
            return True
        if isinstance(expression, ast.Call) and expression.name in {"coalesce", "nullIf", "toString"}:
            if (
                expression.params is not None
                or expression.filter_expr is not None
                or expression.order_by is not None
                or expression.within_group is not None
                or expression.distinct
            ):
                return False
            return all(AccountPersonsCatalog.supports_expression(arg) for arg in expression.args)
        return False

    @staticmethod
    def supports_filters(filters: object) -> bool:
        if filters is None:
            return True
        if isinstance(filters, list):
            return all(AccountPersonsCatalog.supports_filters(item) for item in filters)
        if isinstance(filters, PropertyGroupFilterValue):
            return AccountPersonsCatalog.supports_filters(filters.values)
        return isinstance(filters, PersonPropertyFilter) and not filters.key.startswith("$virt_")

    @staticmethod
    def supports_columns(query: ActorsQuery) -> bool:
        if not query.select:
            return False
        try:
            for column in query.select:
                if column.split("--")[0].strip() == "person_display_name" or column == "person.$delete":
                    continue
                if not AccountPersonsCatalog.supports_expression(parse_expr(column)):
                    return False
            for order in query.orderBy or []:
                if order.split("--")[0].strip().removesuffix(" DESC").removesuffix(" ASC") == "person_display_name":
                    continue
                order_expression = parse_order_expr(order)
                if order_expression.with_fill is not None or not AccountPersonsCatalog.supports_expression(
                    order_expression.expr
                ):
                    return False
        except ExposedHogQLError:
            return False
        return True

    @staticmethod
    def supports_query(query: ActorsQuery, team: Team) -> bool:
        if not all(
            AccountPersonsCatalog.supports_filters(filters) for filters in (query.properties, query.fixedProperties)
        ):
            return False
        if query.filterTestAccounts and any(
            item.get("type") not in {"person", "event"} or str(item.get("key", "")).startswith("$virt_")
            for item in (team.test_account_filters or [])
        ):
            return False
        if any(key.startswith("$virt_") for key in (team.person_display_name_properties or [])):
            return False
        for modifiers in (query.modifiers, query.source.modifiers if query.source else None):
            if modifiers and set(modifiers.model_dump(exclude_none=True)) - {"personsArgMaxVersion"}:
                return False
        return AccountPersonsCatalog.supports_columns(query)

    def __init__(self, team: Team, user: User) -> None:
        self.team = team
        self.user = user
        self.variant: str | None = None
        self.database: Database | None = None
        self.build_duration_ms = 0.0
        self.cache_hit = False
        self.failed = False

    @contextmanager
    def run(self, *, track: bool = True) -> Iterator[None]:
        started_at = perf_counter()
        org_id = str(self.team.organization_id)
        team_id = str(self.team.pk)
        variant = get_feature_flag_or_none(
            ACCOUNT_PERSONS_CATALOG_FLAG,
            str(self.user.distinct_id),
            groups={"organization": org_id, "project": team_id},
            group_properties={"organization": {"id": org_id}, "project": {"id": team_id}},
            person_properties={"email": self.user.email, "is_staff": self.user.is_staff},
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
        if variant not in {"control", "test"}:
            yield
            return
        self.variant = str(variant)
        if not track:
            yield
            return
        properties = {
            "catalog_experiment": ACCOUNT_PERSONS_CATALOG_FLAG,
            "catalog_variant": self.variant,
            f"$feature/{ACCOUNT_PERSONS_CATALOG_FLAG}": self.variant,
        }
        emit_slo_started(
            distinct_id=str(self.user.distinct_id),
            properties=SloStartedProperties(
                area=SloArea.ANALYTIC_PLATFORM,
                operation=SloOperation.ACCOUNT_PERSONS_QUERY,
                team_id=self.team.pk,
            ),
            extra_properties=properties,
        )
        outcome = SloOutcome.FAILURE
        try:
            yield
            outcome = SloOutcome.FAILURE if self.failed else SloOutcome.SUCCESS
        finally:
            emit_slo_completed(
                distinct_id=str(self.user.distinct_id),
                properties=SloCompletedProperties(
                    area=SloArea.ANALYTIC_PLATFORM,
                    operation=SloOperation.ACCOUNT_PERSONS_QUERY,
                    team_id=self.team.pk,
                    outcome=outcome,
                    duration_ms=(perf_counter() - started_at) * 1000,
                ),
                extra_properties={
                    **properties,
                    "cache_hit": self.cache_hit,
                    "catalog_build_ms": self.build_duration_ms,
                },
            )

    def get_database(
        self,
        build_full_database: Callable[[], Database],
        *,
        modifiers: "HogQLQueryModifiers",
        timings: "HogQLTimings",
        user_access_control: "UserAccessControl | None",
    ) -> Database:
        started_at = perf_counter()
        try:
            if self.variant != "test":
                return build_full_database()
            if self.database is None:
                # This experiment is a one-off exception to the builder's restriction on user-written HogQL.
                # It depends on the supports_query allowlist and the existing access checks.
                # Do not copy this pattern to other query paths.
                self.database = Database.create_for_posthog_tables(self.team, modifiers=modifiers, timings=timings)
                self.database.user_access_control = user_access_control
            return self.database
        finally:
            self.build_duration_ms += (perf_counter() - started_at) * 1000
