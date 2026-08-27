from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from django.db import transaction
from django.db.models import Count, OuterRef, Q, QuerySet, Subquery
from django.utils import timezone

import structlog

from posthog.dataclasses import frozen
from posthog.event_usage import report_user_action
from posthog.exceptions_capture import capture_exception
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.user import User

from products.customer_analytics.backend.facade import contracts
from products.customer_analytics.backend.logic.account_filters import (
    ACCOUNT_DIRECT_FIELDS,
    InvalidAccountFilter,
    apply_account_filters,
)
from products.customer_analytics.backend.metrics import record_account_track_rule_run
from products.customer_analytics.backend.models import (
    Account,
    AccountTrackRuleRun,
    AccountTrackRuleRunStatus,
    AccountTrackRuleRunTrigger,
    CustomPropertyDefinition,
    CustomPropertyValue,
    DisplayType,
    TargetType,
    TeamCustomerAnalyticsConfig,
)

logger = structlog.get_logger(__name__)

ACCOUNT_TRACK_RULE_SCHEMA_VERSION = 1
ACCOUNT_TRACK_RULE_MAX_GROUPS = 20
ACCOUNT_TRACK_RULE_MAX_CONDITIONS = 20
ACCOUNT_TRACK_RULE_MAX_VALUES = 100
ACCOUNT_TRACK_RULE_MAX_STRING_LENGTH = 1_000
ACCOUNT_TRACK_RULE_SAMPLE_SIZE = 5
ACCOUNT_TRACK_RULE_BATCH_SIZE = 1_000

ALLOWED_ACCOUNT_FIELDS = frozenset(contracts.AccountTableField) - {
    contracts.AccountTableField.CHURNED_AT,
    contracts.AccountTableField.IGNORED_AT,
}


class AccountTrackRuleValidationError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__(errors[0] if errors else "Invalid account Track Rules.")


class AccountTrackRuleVersionConflict(ValueError):
    pass


class AccountTrackRuleRunError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedAccountTrackRules:
    config: contracts.AccountTrackRulesConfig
    custom_property_display_types: dict[UUID, DisplayType]


@dataclass(frozen=True)
class AccountTrackRuleBatchResult:
    status: str
    processed: int


@frozen
class EnabledAccountTrackRuleConfig:
    team_id: int
    config_version: int
    enabled_at: datetime | None
    first_run_at: datetime | None
    last_success_at: datetime | None


@dataclass(frozen=True)
class EnabledAccountTrackRuleConfigPage:
    configs: tuple[EnabledAccountTrackRuleConfig, ...]
    next_team_id: int | None


def _config_to_json(config: contracts.AccountTrackRulesConfig) -> dict[str, Any]:
    groups = []
    for group in config.groups:
        conditions = []
        for condition in group.conditions:
            field: dict[str, Any] = {"kind": condition.field.kind.value}
            if condition.field.kind == contracts.AccountTrackRuleFieldKind.ACCOUNT_FIELD:
                field["field"] = condition.field.field.value if condition.field.field else None
            else:
                field["definition_id"] = str(condition.field.definition_id)
            conditions.append(
                {
                    "field": field,
                    "operator": condition.operator,
                    "values": list(condition.values),
                }
            )
        groups.append({"conditions": conditions})
    return {
        "schema_version": config.schema_version,
        "version": config.version,
        "enabled": config.enabled,
        "groups": groups,
    }


def _parse_rule_field(raw_field: Any, path: str) -> contracts.AccountTrackRuleField:
    if not isinstance(raw_field, dict):
        raise AccountTrackRuleValidationError([f"{path} must be an object."])
    try:
        kind = contracts.AccountTrackRuleFieldKind(raw_field.get("kind"))
    except ValueError as error:
        raise AccountTrackRuleValidationError([f"{path}.kind is unknown."]) from error

    if kind == contracts.AccountTrackRuleFieldKind.ACCOUNT_FIELD:
        if set(raw_field) != {"kind", "field"}:
            raise AccountTrackRuleValidationError([f"{path} must contain only kind and field."])
        try:
            field = contracts.AccountTableField(raw_field.get("field"))
        except ValueError as error:
            raise AccountTrackRuleValidationError([f"{path}.field is unknown."]) from error
        if field not in ALLOWED_ACCOUNT_FIELDS:
            raise AccountTrackRuleValidationError([f"{path}.field cannot be used in Track Rules."])
        return contracts.AccountTrackRuleField(kind=kind, field=field)

    if set(raw_field) != {"kind", "definition_id"}:
        raise AccountTrackRuleValidationError([f"{path} must contain only kind and definition_id."])
    try:
        definition_id = UUID(str(raw_field.get("definition_id")))
    except (TypeError, ValueError) as error:
        raise AccountTrackRuleValidationError([f"{path}.definition_id must be a UUID."]) from error
    return contracts.AccountTrackRuleField(kind=kind, definition_id=definition_id)


def _parse_condition(raw_condition: Any, path: str) -> contracts.AccountTrackRuleCondition:
    if not isinstance(raw_condition, dict) or set(raw_condition) != {"field", "operator", "values"}:
        raise AccountTrackRuleValidationError([f"{path} must contain field, operator, and values."])
    field = _parse_rule_field(raw_condition["field"], f"{path}.field")
    operator = raw_condition["operator"]
    if not isinstance(operator, str):
        raise AccountTrackRuleValidationError([f"{path}.operator must be a string."])
    values = raw_condition["values"]
    if not isinstance(values, list):
        raise AccountTrackRuleValidationError([f"{path}.values must be a list."])
    if len(values) > ACCOUNT_TRACK_RULE_MAX_VALUES:
        raise AccountTrackRuleValidationError(
            [f"{path}.values cannot contain more than {ACCOUNT_TRACK_RULE_MAX_VALUES} values."]
        )
    for value in values:
        if not isinstance(value, str | int | float | bool) or value is None:
            raise AccountTrackRuleValidationError([f"{path}.values contains an unsupported value."])
        if isinstance(value, str) and len(value) > ACCOUNT_TRACK_RULE_MAX_STRING_LENGTH:
            raise AccountTrackRuleValidationError(
                [f"{path}.values strings cannot exceed {ACCOUNT_TRACK_RULE_MAX_STRING_LENGTH} characters."]
            )
    if field.kind == contracts.AccountTrackRuleFieldKind.ACCOUNT_FIELD and any(
        not isinstance(value, str) for value in values
    ):
        raise AccountTrackRuleValidationError([f"{path}.values for account fields must be strings."])
    return contracts.AccountTrackRuleCondition(field=field, operator=operator, values=tuple(values))


def _config_from_json(raw_config: dict[str, Any]) -> contracts.AccountTrackRulesConfig:
    return contracts.AccountTrackRulesConfig(
        schema_version=raw_config["schema_version"],
        version=raw_config["version"],
        enabled=raw_config["enabled"],
        groups=tuple(
            contracts.AccountTrackRuleGroup(
                conditions=tuple(
                    _parse_condition(condition, f"groups[{group_index}].conditions[{condition_index}]")
                    for condition_index, condition in enumerate(group["conditions"])
                )
            )
            for group_index, group in enumerate(raw_config["groups"])
        ),
    )


def parse_account_track_rules(team_id: int, raw_config: Any) -> ParsedAccountTrackRules:
    if not isinstance(raw_config, dict):
        raise AccountTrackRuleValidationError(["Track Rules must be an object."])
    if set(raw_config) != {"schema_version", "version", "enabled", "groups"}:
        raise AccountTrackRuleValidationError(
            ["Track Rules must contain schema_version, version, enabled, and groups."]
        )
    if raw_config["schema_version"] != ACCOUNT_TRACK_RULE_SCHEMA_VERSION:
        raise AccountTrackRuleValidationError(["Unsupported Track Rules schema version."])
    if (
        not isinstance(raw_config["version"], int)
        or isinstance(raw_config["version"], bool)
        or raw_config["version"] < 0
    ):
        raise AccountTrackRuleValidationError(["Track Rules version must be a non-negative integer."])
    if not isinstance(raw_config["enabled"], bool):
        raise AccountTrackRuleValidationError(["Track Rules enabled must be a boolean."])
    raw_groups = raw_config["groups"]
    if not isinstance(raw_groups, list):
        raise AccountTrackRuleValidationError(["Track Rules groups must be a list."])
    if len(raw_groups) > ACCOUNT_TRACK_RULE_MAX_GROUPS:
        raise AccountTrackRuleValidationError(
            [f"Track Rules cannot contain more than {ACCOUNT_TRACK_RULE_MAX_GROUPS} groups."]
        )
    if raw_config["enabled"] and not raw_groups:
        raise AccountTrackRuleValidationError(["Enabled Track Rules require at least one group."])

    groups: list[contracts.AccountTrackRuleGroup] = []
    custom_property_ids: set[UUID] = set()
    for group_index, raw_group in enumerate(raw_groups):
        path = f"groups[{group_index}]"
        if not isinstance(raw_group, dict) or set(raw_group) != {"conditions"}:
            raise AccountTrackRuleValidationError([f"{path} must contain conditions."])
        raw_conditions = raw_group["conditions"]
        if not isinstance(raw_conditions, list) or not raw_conditions:
            raise AccountTrackRuleValidationError([f"{path}.conditions must contain at least one condition."])
        if len(raw_conditions) > ACCOUNT_TRACK_RULE_MAX_CONDITIONS:
            raise AccountTrackRuleValidationError(
                [f"{path} cannot contain more than {ACCOUNT_TRACK_RULE_MAX_CONDITIONS} conditions."]
            )
        conditions = tuple(
            _parse_condition(raw_condition, f"{path}.conditions[{condition_index}]")
            for condition_index, raw_condition in enumerate(raw_conditions)
        )
        custom_property_ids.update(
            condition.field.definition_id
            for condition in conditions
            if condition.field.kind == contracts.AccountTrackRuleFieldKind.CUSTOM_PROPERTY
            and condition.field.definition_id is not None
        )
        groups.append(contracts.AccountTrackRuleGroup(conditions=conditions))

    display_types = {
        definition_id: DisplayType(display_type)
        for definition_id, display_type in CustomPropertyDefinition.objects.for_team(team_id)
        .filter(id__in=custom_property_ids, target_type=TargetType.ACCOUNT)
        .values_list("id", "display_type")
    }
    if missing_ids := custom_property_ids - set(display_types):
        raise AccountTrackRuleValidationError(
            [f"Unknown account custom property definition: {sorted(str(value) for value in missing_ids)[0]}."]
        )

    config = contracts.AccountTrackRulesConfig(
        schema_version=ACCOUNT_TRACK_RULE_SCHEMA_VERSION,
        version=raw_config["version"],
        enabled=raw_config["enabled"],
        groups=tuple(groups),
    )
    parsed = ParsedAccountTrackRules(config=config, custom_property_display_types=display_types)
    _validate_compiler_inputs(team_id, parsed)
    return parsed


def _condition_to_filter(condition: contracts.AccountTrackRuleCondition) -> contracts.AccountTableFilter:
    try:
        if condition.field.kind == contracts.AccountTrackRuleFieldKind.ACCOUNT_FIELD:
            assert condition.field.field is not None
            return contracts.AccountTableFieldFilter(
                field=condition.field.field,
                operator=contracts.AccountTableFieldOperator(condition.operator),
                values=tuple(str(value) for value in condition.values),
            )
        assert condition.field.definition_id is not None
        return contracts.AccountTableCustomPropertyFilter(
            definition_id=condition.field.definition_id,
            operator=contracts.AccountTableCustomPropertyOperator(condition.operator),
            values=condition.values,
        )
    except ValueError as error:
        raise AccountTrackRuleValidationError([f"Unknown operator: {condition.operator}."]) from error


def _group_filters(group: contracts.AccountTrackRuleGroup) -> tuple[contracts.AccountTableFilter, ...]:
    return tuple(_condition_to_filter(condition) for condition in group.conditions)


def _validate_compiler_inputs(team_id: int, parsed: ParsedAccountTrackRules) -> None:
    base = Account.objects.for_team(team_id).all()
    try:
        for group in parsed.config.groups:
            apply_account_filters(
                base,
                team_id=team_id,
                filters=_group_filters(group),
                custom_property_display_types=parsed.custom_property_display_types,
            )
    except (InvalidAccountFilter, TypeError) as error:
        raise AccountTrackRuleValidationError([str(error)]) from error


def matching_accounts_queryset(
    queryset: QuerySet[Account], *, team_id: int, parsed: ParsedAccountTrackRules
) -> QuerySet[Account]:
    if not parsed.config.groups:
        return queryset.none()
    matching_groups = Q()
    for group in parsed.config.groups:
        group_matches = apply_account_filters(
            queryset.order_by(),
            team_id=team_id,
            filters=_group_filters(group),
            custom_property_display_types=parsed.custom_property_display_types,
        )
        matching_groups |= Q(id__in=Subquery(group_matches.values("id")))
    return queryset.filter(matching_groups)


def get_account_track_rules(team_id: int) -> contracts.AccountTrackRulesConfig:
    row, _ = TeamCustomerAnalyticsConfig.objects.get_or_create(team_id=team_id)
    try:
        return _config_from_json(row.account_track_rules)
    except (AccountTrackRuleValidationError, KeyError, TypeError, ValueError):
        return contracts.AccountTrackRulesConfig()


def update_account_track_rules(
    *,
    team_id: int,
    raw_config: dict[str, Any],
    user: User,
    organization_id: UUID,
    was_impersonated: bool,
) -> contracts.AccountTrackRulesConfig:
    parsed = parse_account_track_rules(team_id, raw_config)
    with transaction.atomic():
        row, _ = TeamCustomerAnalyticsConfig.objects.select_for_update().get_or_create(team_id=team_id)
        current_version = row.account_track_rules.get("version", 0)
        if parsed.config.version != current_version:
            raise AccountTrackRuleVersionConflict("Track Rules changed since this page loaded. Reload and try again.")
        candidate = contracts.AccountTrackRulesConfig(
            schema_version=ACCOUNT_TRACK_RULE_SCHEMA_VERSION,
            version=current_version + 1,
            enabled=parsed.config.enabled,
            groups=parsed.config.groups,
        )
        candidate_json = _config_to_json(candidate)
        current_without_version = {**row.account_track_rules, "version": candidate.version}
        if current_without_version == candidate_json:
            return contracts.AccountTrackRulesConfig(
                schema_version=ACCOUNT_TRACK_RULE_SCHEMA_VERSION,
                version=current_version,
                enabled=candidate.enabled,
                groups=candidate.groups,
            )
        was_enabled = bool(row.account_track_rules.get("enabled", False))
        previous_summary = {
            "version": current_version,
            "enabled": was_enabled,
            "group_count": len(row.account_track_rules.get("groups", [])),
            "condition_count": sum(
                len(group.get("conditions", [])) for group in row.account_track_rules.get("groups", [])
            ),
        }
        current_summary = {
            "version": candidate.version,
            "enabled": candidate.enabled,
            "group_count": len(candidate.groups),
            "condition_count": sum(len(group.conditions) for group in candidate.groups),
        }
        row.account_track_rules = candidate_json
        if candidate.enabled and not was_enabled:
            row.account_track_rules_enabled_at = timezone.now()
        elif not candidate.enabled:
            row.account_track_rules_enabled_at = None
        row.save(update_fields=["account_track_rules", "account_track_rules_enabled_at"])

        try:
            log_activity(
                organization_id=organization_id,
                team_id=team_id,
                user=user,
                was_impersonated=was_impersonated,
                item_id=str(team_id),
                scope="TeamCustomerAnalyticsConfig",
                activity="updated",
                detail=Detail(
                    name="Account Track Rules",
                    changes=[
                        Change(
                            type="TeamCustomerAnalyticsConfig",
                            action="changed",
                            field="account_track_rules",
                            before=previous_summary,
                            after=current_summary,
                        )
                    ],
                ),
            )
        except Exception as error:
            capture_exception(error)
    return candidate


def _rule_field_key(field: contracts.AccountTrackRuleField) -> str:
    if field.kind == contracts.AccountTrackRuleFieldKind.ACCOUNT_FIELD:
        assert field.field is not None
        return f"account_field:{field.field.value}"
    assert field.definition_id is not None
    return f"custom_property:{field.definition_id}"


def _rule_fields(config: contracts.AccountTrackRulesConfig) -> tuple[contracts.AccountTrackRuleField, ...]:
    fields: list[contracts.AccountTrackRuleField] = []
    for group in config.groups:
        for condition in group.conditions:
            if condition.field not in fields:
                fields.append(condition.field)
    return tuple(fields)


def _serialize_rule_value(value: Any) -> float | bool | str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    if value is None or isinstance(value, bool | float | int | str):
        return value
    return str(value)


def _custom_property_value(row: CustomPropertyValue) -> float | bool | str | None:
    for value in (row.value_str, row.value_bool, row.value_num, row.value_datetime):
        if value is not None:
            return _serialize_rule_value(value)
    return None


def _sample_accounts(
    queryset: QuerySet[Account], *, team_id: int, config: contracts.AccountTrackRulesConfig
) -> tuple[contracts.AccountTrackRuleSample, ...]:
    accounts = list(queryset.order_by("id")[:ACCOUNT_TRACK_RULE_SAMPLE_SIZE])
    fields = _rule_fields(config)
    custom_definition_ids = [
        field.definition_id
        for field in fields
        if field.kind == contracts.AccountTrackRuleFieldKind.CUSTOM_PROPERTY and field.definition_id is not None
    ]
    custom_values = {
        (value.account_id, value.definition_id): _custom_property_value(value)
        for value in CustomPropertyValue.objects.for_team(team_id).filter(
            account_id__in=[account.id for account in accounts],
            definition_id__in=custom_definition_ids,
            is_deleted=False,
        )
    }

    samples = []
    for account in accounts:
        rule_values = {}
        for field in fields:
            if field.kind == contracts.AccountTrackRuleFieldKind.ACCOUNT_FIELD:
                assert field.field is not None
                direct_field = ACCOUNT_DIRECT_FIELDS.get(field.field)
                value = getattr(account, direct_field) if direct_field else account._properties.get(field.field.value)
            else:
                assert field.definition_id is not None
                value = custom_values.get((account.id, field.definition_id))
            rule_values[_rule_field_key(field)] = _serialize_rule_value(value)
        samples.append(
            contracts.AccountTrackRuleSample(
                id=account.id,
                name=account.name,
                external_id=account.external_id,
                rule_values=rule_values,
            )
        )
    return tuple(samples)


def preview_account_track_rules(
    team_id: int, raw_config: dict[str, Any] | None = None
) -> contracts.AccountTrackRulePreview:
    if raw_config is None:
        row, _ = TeamCustomerAnalyticsConfig.objects.get_or_create(team_id=team_id)
        raw_config = row.account_track_rules
    parsed = parse_account_track_rules(team_id, raw_config)
    active = Account.objects.for_team(team_id).filter(churned_at__isnull=True)
    matching = matching_accounts_queryset(active, team_id=team_id, parsed=parsed)
    nonmatching = active.exclude(id__in=Subquery(matching.order_by().values("id")))

    matching_counts = matching.aggregate(
        total=Count("id"),
        restored=Count("id", filter=Q(ignored_at__isnull=False)),
    )
    nonmatching_counts = nonmatching.aggregate(
        total=Count("id"),
        newly_ignored=Count("id", filter=Q(ignored_at__isnull=True)),
    )
    tracked = matching_counts["total"]
    ignored = nonmatching_counts["total"]
    tracked_samples = _sample_accounts(matching, team_id=team_id, config=parsed.config)
    ignored_samples = _sample_accounts(nonmatching, team_id=team_id, config=parsed.config)
    return contracts.AccountTrackRulePreview(
        config_version=parsed.config.version,
        eligible_active=tracked + ignored,
        skipped_churned=Account.objects.for_team(team_id).filter(churned_at__isnull=False).count(),
        tracked=tracked,
        ignored=ignored,
        newly_ignored=nonmatching_counts["newly_ignored"],
        restored=matching_counts["restored"],
        tracked_samples=tracked_samples,
        ignored_samples=ignored_samples,
    )


def to_run_view(run: AccountTrackRuleRun) -> contracts.AccountTrackRuleRunView:
    return contracts.AccountTrackRuleRunView(
        id=run.id,
        config_version=run.config_version,
        trigger=run.trigger,
        status=run.status,
        eligible_active=run.eligible_active,
        skipped_churned=run.skipped_churned,
        tracked=run.tracked,
        ignored=run.ignored,
        newly_ignored=run.newly_ignored,
        restored=run.restored,
        started_at=run.started_at,
        finished_at=run.finished_at,
        error=run.error,
        created_by=run.created_by_id,
        created_at=run.created_at,
    )


def list_account_track_rule_runs(
    team_id: int, *, offset: int, limit: int
) -> tuple[list[contracts.AccountTrackRuleRunView], int]:
    queryset = AccountTrackRuleRun.objects.for_team(team_id).order_by("-created_at")
    return [to_run_view(run) for run in queryset[offset : offset + limit]], queryset.count()


def list_enabled_account_track_rule_configs(
    *, after_team_id: int = 0, limit: int = 100
) -> EnabledAccountTrackRuleConfigPage:
    team_runs = AccountTrackRuleRun.objects.unscoped().filter(team_id=OuterRef("team_id"))
    first_run = team_runs.order_by("created_at").values("created_at")[:1]
    latest_success = (
        team_runs.filter(
            status=AccountTrackRuleRunStatus.COMPLETED,
            finished_at__isnull=False,
        )
        .order_by("-finished_at")
        .values("finished_at")[:1]
    )
    rows = list(
        TeamCustomerAnalyticsConfig.objects.filter(
            team_id__gt=after_team_id,
            account_track_rules__enabled=True,
        )
        .annotate(
            first_run_at=Subquery(first_run),
            last_success_at=Subquery(latest_success),
        )
        .order_by("team_id")
        .values(
            "team_id",
            "account_track_rules",
            "account_track_rules_enabled_at",
            "first_run_at",
            "last_success_at",
        )[:limit]
    )
    configs = tuple(
        EnabledAccountTrackRuleConfig(
            team_id=row["team_id"],
            config_version=row["account_track_rules"].get("version", 0),
            enabled_at=row["account_track_rules_enabled_at"],
            first_run_at=row["first_run_at"],
            last_success_at=row["last_success_at"],
        )
        for row in rows
    )
    return EnabledAccountTrackRuleConfigPage(
        configs=configs,
        next_team_id=configs[-1].team_id if configs and len(configs) == limit else None,
    )


def create_account_track_rule_run(
    *,
    team_id: int,
    idempotency_key: UUID,
    user_id: int | None,
    trigger: str = AccountTrackRuleRunTrigger.MANUAL,
    expected_config_version: int | None = None,
) -> tuple[AccountTrackRuleRun, bool]:
    with transaction.atomic():
        existing = AccountTrackRuleRun.objects.for_team(team_id).filter(idempotency_key=idempotency_key).first()
        if existing is not None:
            return existing, False

        row, _ = TeamCustomerAnalyticsConfig.objects.select_for_update().get_or_create(team_id=team_id)
        current_version = row.account_track_rules.get("version", 0)
        if expected_config_version is not None and current_version != expected_config_version:
            raise AccountTrackRuleVersionConflict("Track Rules changed before the scheduled run started.")

        parsed = parse_account_track_rules(team_id, row.account_track_rules)
        if not parsed.config.enabled:
            raise AccountTrackRuleRunError("Enable and save Track Rules before running them.")
        return AccountTrackRuleRun.objects.for_team(team_id).get_or_create(
            idempotency_key=idempotency_key,
            defaults={
                "team_id": team_id,
                "created_by_id": user_id,
                "config_version": parsed.config.version,
                "trigger": trigger,
            },
        )


def _run_duration_seconds(run: AccountTrackRuleRun) -> float | None:
    started_at = run.started_at
    finished_at = run.finished_at
    if started_at is None or finished_at is None:
        return None
    return (finished_at - started_at).total_seconds()


def _report_run_outcome(team_id: int, run_id: UUID) -> None:
    run = AccountTrackRuleRun.objects.for_team(team_id).select_related("created_by", "team").filter(id=run_id).first()
    if run is None or run.created_by is None:
        return
    event = (
        "account track rules run completed"
        if run.status == AccountTrackRuleRunStatus.COMPLETED
        else "account track rules run failed"
    )
    properties = {
        "config_version": run.config_version,
        "trigger": run.trigger,
        "status": run.status,
        "eligible_active": run.eligible_active,
        "skipped_churned": run.skipped_churned,
        "tracked": run.tracked,
        "ignored": run.ignored,
        "newly_ignored": run.newly_ignored,
        "restored": run.restored,
        "duration_seconds": _run_duration_seconds(run),
    }
    try:
        report_user_action(run.created_by, event, properties, team=run.team)
    except Exception as error:
        capture_exception(error, {"team_id": team_id, "run_id": str(run_id), "stage": "report_outcome"})


def _report_run_outcome_after_commit(team_id: int, run_id: UUID) -> None:
    transaction.on_commit(lambda: _report_run_outcome(team_id, run_id))


def _record_terminal_run(run: AccountTrackRuleRun) -> None:
    duration_seconds = _run_duration_seconds(run)
    record_account_track_rule_run(
        trigger=run.trigger,
        status=run.status,
        duration_seconds=duration_seconds,
        eligible_active=run.eligible_active,
        skipped_churned=run.skipped_churned,
        tracked=run.tracked,
        ignored=run.ignored,
        newly_ignored=run.newly_ignored,
        restored=run.restored,
    )


def process_next_account_track_rule_batch(
    team_id: int, run_id: UUID, *, batch_size: int = ACCOUNT_TRACK_RULE_BATCH_SIZE
) -> AccountTrackRuleBatchResult:
    with transaction.atomic():
        run = AccountTrackRuleRun.objects.for_team(team_id).select_for_update().get(id=run_id)
        if run.status in {
            AccountTrackRuleRunStatus.COMPLETED,
            AccountTrackRuleRunStatus.FAILED,
            AccountTrackRuleRunStatus.STALE,
        }:
            return AccountTrackRuleBatchResult(status=run.status, processed=run.processed)

        config_row = TeamCustomerAnalyticsConfig.objects.select_for_update().get(team_id=run.team_id)
        if config_row.account_track_rules.get("version") != run.config_version:
            run.status = AccountTrackRuleRunStatus.STALE
            run.finished_at = timezone.now()
            run.error = "Track Rules changed while this run was in progress."
            run.save(update_fields=["status", "finished_at", "error"])
            logger.warning(
                "account_track_rule_run_stale",
                team_id=run.team_id,
                run_id=str(run.id),
                config_version=run.config_version,
                trigger=run.trigger,
                status=run.status,
                processed=run.processed,
                duration_seconds=_run_duration_seconds(run),
            )
            _record_terminal_run(run)
            _report_run_outcome_after_commit(run.team_id, run.id)
            return AccountTrackRuleBatchResult(status=run.status, processed=run.processed)

        try:
            parsed = parse_account_track_rules(run.team_id, config_row.account_track_rules)
        except AccountTrackRuleValidationError:
            run.status = AccountTrackRuleRunStatus.FAILED
            run.finished_at = timezone.now()
            run.error = "Track Rules are no longer valid."
            run.save(update_fields=["status", "finished_at", "error"])
            logger.warning(
                "account_track_rule_run_invalid_config",
                team_id=run.team_id,
                run_id=str(run.id),
                config_version=run.config_version,
                trigger=run.trigger,
                status=run.status,
                duration_seconds=_run_duration_seconds(run),
            )
            _record_terminal_run(run)
            _report_run_outcome_after_commit(run.team_id, run.id)
            return AccountTrackRuleBatchResult(status=run.status, processed=run.processed)

        if run.status == AccountTrackRuleRunStatus.PENDING:
            run.status = AccountTrackRuleRunStatus.RUNNING
            run.started_at = timezone.now()
            run.eligible_active = Account.objects.for_team(run.team_id).filter(churned_at__isnull=True).count()
            run.skipped_churned = Account.objects.for_team(run.team_id).filter(churned_at__isnull=False).count()
            logger.info(
                "account_track_rule_run_started",
                team_id=run.team_id,
                run_id=str(run.id),
                config_version=run.config_version,
                trigger=run.trigger,
                status=run.status,
                eligible_active=run.eligible_active,
                skipped_churned=run.skipped_churned,
            )

        active = Account.objects.for_team(run.team_id).filter(churned_at__isnull=True)
        if run.last_account_id:
            active = active.filter(id__gt=run.last_account_id)
        account_ids = list(active.order_by("id").values_list("id", flat=True)[:batch_size])
        if not account_ids:
            run.status = AccountTrackRuleRunStatus.COMPLETED
            run.finished_at = timezone.now()
            run.save(
                update_fields=[
                    "status",
                    "started_at",
                    "finished_at",
                    "eligible_active",
                    "skipped_churned",
                ]
            )
            logger.info(
                "account_track_rule_run_completed",
                team_id=run.team_id,
                run_id=str(run.id),
                config_version=run.config_version,
                trigger=run.trigger,
                status=run.status,
                eligible_active=run.eligible_active,
                skipped_churned=run.skipped_churned,
                tracked=run.tracked,
                ignored=run.ignored,
                newly_ignored=run.newly_ignored,
                restored=run.restored,
                duration_seconds=_run_duration_seconds(run),
            )
            _record_terminal_run(run)
            _report_run_outcome_after_commit(run.team_id, run.id)
            return AccountTrackRuleBatchResult(status=run.status, processed=run.processed)

        active_batch_ids = set(
            Account.objects.for_team(run.team_id)
            .select_for_update()
            .filter(id__in=account_ids, churned_at__isnull=True)
            .values_list("id", flat=True)
        )
        batch = Account.objects.for_team(run.team_id).filter(id__in=active_batch_ids, churned_at__isnull=True)
        matching = matching_accounts_queryset(batch, team_id=run.team_id, parsed=parsed)
        matching_ids = set(matching.values_list("id", flat=True))
        nonmatching_ids = active_batch_ids - matching_ids
        restored_ids = set(batch.filter(id__in=matching_ids, ignored_at__isnull=False).values_list("id", flat=True))
        newly_ignored_ids = set(
            batch.filter(id__in=nonmatching_ids, ignored_at__isnull=True).values_list("id", flat=True)
        )

        if restored_ids:
            Account.objects.for_team(run.team_id).filter(id__in=restored_ids, churned_at__isnull=True).update(
                ignored_at=None
            )
        if newly_ignored_ids:
            Account.objects.for_team(run.team_id).filter(id__in=newly_ignored_ids, churned_at__isnull=True).update(
                ignored_at=timezone.now()
            )

        run.tracked += len(matching_ids)
        run.ignored += len(nonmatching_ids)
        run.restored += len(restored_ids)
        run.newly_ignored += len(newly_ignored_ids)
        run.processed += len(active_batch_ids)
        run.last_account_id = account_ids[-1]
        run.save(
            update_fields=[
                "status",
                "started_at",
                "eligible_active",
                "skipped_churned",
                "tracked",
                "ignored",
                "restored",
                "newly_ignored",
                "processed",
                "last_account_id",
            ]
        )
        logger.info(
            "account_track_rule_batch_completed",
            team_id=run.team_id,
            run_id=str(run.id),
            config_version=run.config_version,
            trigger=run.trigger,
            status=run.status,
            processed=run.processed,
            batch_size=len(account_ids),
            tracked=run.tracked,
            ignored=run.ignored,
            newly_ignored=run.newly_ignored,
            restored=run.restored,
        )
        return AccountTrackRuleBatchResult(status=run.status, processed=run.processed)


def fail_account_track_rule_run(team_id: int, run_id: UUID) -> None:
    updated = (
        AccountTrackRuleRun.objects.for_team(team_id)
        .filter(
            id=run_id,
            status__in=[AccountTrackRuleRunStatus.PENDING, AccountTrackRuleRunStatus.RUNNING],
        )
        .update(
            status=AccountTrackRuleRunStatus.FAILED,
            finished_at=timezone.now(),
            error="The Track Rules run failed. Try again or inspect Error Tracking.",
        )
    )
    if updated:
        run = AccountTrackRuleRun.objects.for_team(team_id).get(id=run_id)
        logger.error(
            "account_track_rule_run_failed",
            team_id=team_id,
            run_id=str(run_id),
            config_version=run.config_version,
            trigger=run.trigger,
            status=run.status,
            eligible_active=run.eligible_active,
            skipped_churned=run.skipped_churned,
            tracked=run.tracked,
            ignored=run.ignored,
            newly_ignored=run.newly_ignored,
            restored=run.restored,
            duration_seconds=_run_duration_seconds(run),
        )
        _record_terminal_run(run)
        if run.trigger == AccountTrackRuleRunTrigger.SCHEDULED:
            capture_exception(
                AccountTrackRuleRunError("An Account Track Rules run failed."),
                {
                    "team_id": team_id,
                    "run_id": str(run_id),
                    "config_version": run.config_version,
                    "trigger": run.trigger,
                },
            )
        _report_run_outcome(team_id, run_id)
