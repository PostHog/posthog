from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.core import signing
from django.db import transaction
from django.db.models import Q, QuerySet, Subquery
from django.utils import timezone

import structlog

from posthog.event_usage import report_user_action
from posthog.exceptions_capture import capture_exception
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.models.user import User

from products.customer_analytics.backend.facade import contracts
from products.customer_analytics.backend.logic.account_filters import InvalidAccountFilter, apply_account_filters
from products.customer_analytics.backend.models import (
    Account,
    AccountTrackRuleRun,
    AccountTrackRuleRunStatus,
    CustomPropertyDefinition,
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
ACCOUNT_TRACK_RULE_PREVIEW_MAX_AGE_SECONDS = 60 * 60
ACCOUNT_TRACK_RULE_PREVIEW_SALT = "customer-analytics-account-track-rules-preview-v1"

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


class AccountTrackRulePreviewError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedAccountTrackRules:
    config: contracts.AccountTrackRulesConfig
    custom_property_display_types: dict[UUID, DisplayType]


@dataclass(frozen=True)
class AccountTrackRuleBatchResult:
    status: str
    processed: int


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
        previous_summary = {
            "version": current_version,
            "enabled": bool(row.account_track_rules.get("enabled", False)),
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
        row.save(update_fields=["account_track_rules"])

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


def _config_digest(config: contracts.AccountTrackRulesConfig) -> str:
    payload = json.dumps(_config_to_json(config), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _create_preview_token(team_id: int, config: contracts.AccountTrackRulesConfig) -> str:
    return signing.dumps(
        {"team_id": team_id, "version": config.version, "digest": _config_digest(config)},
        salt=ACCOUNT_TRACK_RULE_PREVIEW_SALT,
        compress=True,
    )


def validate_preview_token(team_id: int, config: contracts.AccountTrackRulesConfig, token: str) -> None:
    try:
        payload = signing.loads(
            token,
            salt=ACCOUNT_TRACK_RULE_PREVIEW_SALT,
            max_age=ACCOUNT_TRACK_RULE_PREVIEW_MAX_AGE_SECONDS,
        )
    except signing.BadSignature as error:
        raise AccountTrackRulePreviewError("Preview this Track Rules version again before running it.") from error
    expected = {"team_id": team_id, "version": config.version, "digest": _config_digest(config)}
    if payload != expected:
        raise AccountTrackRulePreviewError("Preview this Track Rules version again before running it.")


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

    tracked = matching.count()
    ignored = nonmatching.count()
    tracked_samples = tuple(
        contracts.AccountTrackRuleSample(id=id_, name=name)
        for id_, name in matching.order_by("id").values_list("id", "name")[:ACCOUNT_TRACK_RULE_SAMPLE_SIZE]
    )
    ignored_samples = tuple(
        contracts.AccountTrackRuleSample(id=id_, name=name)
        for id_, name in nonmatching.order_by("id").values_list("id", "name")[:ACCOUNT_TRACK_RULE_SAMPLE_SIZE]
    )
    return contracts.AccountTrackRulePreview(
        config_version=parsed.config.version,
        eligible_active=tracked + ignored,
        skipped_churned=Account.objects.for_team(team_id).filter(churned_at__isnull=False).count(),
        tracked=tracked,
        ignored=ignored,
        newly_ignored=nonmatching.filter(ignored_at__isnull=True).count(),
        restored=matching.filter(ignored_at__isnull=False).count(),
        tracked_samples=tracked_samples,
        ignored_samples=ignored_samples,
        preview_token=_create_preview_token(team_id, parsed.config),
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


def create_account_track_rule_run(
    *,
    team_id: int,
    config_version: int,
    preview_token: str,
    idempotency_key: UUID,
    user_id: int,
) -> tuple[AccountTrackRuleRun, bool]:
    row, _ = TeamCustomerAnalyticsConfig.objects.get_or_create(team_id=team_id)
    parsed = parse_account_track_rules(team_id, row.account_track_rules)
    if not parsed.config.enabled:
        raise AccountTrackRulePreviewError("Enable Track Rules before running them.")
    if parsed.config.version != config_version:
        raise AccountTrackRulePreviewError("Preview this Track Rules version again before running it.")
    validate_preview_token(team_id, parsed.config, preview_token)
    return AccountTrackRuleRun.objects.for_team(team_id).get_or_create(
        idempotency_key=idempotency_key,
        defaults={
            "team_id": team_id,
            "created_by_id": user_id,
            "config_version": config_version,
        },
    )


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
        "duration_seconds": (
            (run.finished_at - run.started_at).total_seconds()
            if run.finished_at is not None and run.started_at is not None
            else None
        ),
    }
    try:
        report_user_action(run.created_by, event, properties, team=run.team)
    except Exception as error:
        capture_exception(error, {"team_id": team_id, "run_id": str(run_id), "stage": "report_outcome"})


def _report_run_outcome_after_commit(team_id: int, run_id: UUID) -> None:
    transaction.on_commit(lambda: _report_run_outcome(team_id, run_id))


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
                processed=run.processed,
            )
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
            )
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
                eligible_active=run.eligible_active,
                skipped_churned=run.skipped_churned,
                tracked=run.tracked,
                ignored=run.ignored,
                newly_ignored=run.newly_ignored,
                restored=run.restored,
                duration_seconds=(run.finished_at - run.started_at).total_seconds() if run.started_at else None,
            )
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
            processed=run.processed,
            batch_size=len(account_ids),
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
        logger.error("account_track_rule_run_failed", team_id=team_id, run_id=str(run_id))
        _report_run_outcome(team_id, run_id)
