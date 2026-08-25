from datetime import UTC, datetime, time, timedelta
from typing import cast
from uuid import UUID

from django.db.models import Exists, OuterRef, Q, QuerySet
from django.db.models.fields.json import KeyTextTransform
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from posthog.models.tagged_item import TaggedItem

from products.customer_analytics.backend.facade import contracts
from products.customer_analytics.backend.models import Account, AccountRelationship, CustomPropertyValue, DisplayType
from products.customer_analytics.backend.models.custom_property_definition import DATA_TYPE_BY_DISPLAY_TYPE, DataType


class InvalidAccountFilter(ValueError):
    pass


ACCOUNT_TEXT_FIELDS = frozenset(
    {
        contracts.AccountTableField.NAME,
        contracts.AccountTableField.EXTERNAL_ID,
        contracts.AccountTableField.STRIPE_CUSTOMER_ID,
        contracts.AccountTableField.HUBSPOT_DEAL_ID,
        contracts.AccountTableField.BILLING_ID,
        contracts.AccountTableField.SFDC_ID,
        contracts.AccountTableField.ZENDESK_ID,
    }
)
ACCOUNT_DATETIME_FIELDS = frozenset(
    {
        contracts.AccountTableField.CREATED_AT,
        contracts.AccountTableField.UPDATED_AT,
        contracts.AccountTableField.CHURNED_AT,
        contracts.AccountTableField.IGNORED_AT,
    }
)
ACCOUNT_DIRECT_FIELDS = {
    contracts.AccountTableField.NAME: "name",
    contracts.AccountTableField.EXTERNAL_ID: "external_id",
    contracts.AccountTableField.CREATED_AT: "created_at",
    contracts.AccountTableField.UPDATED_AT: "updated_at",
    contracts.AccountTableField.CHURNED_AT: "churned_at",
    contracts.AccountTableField.IGNORED_AT: "ignored_at",
}


def _coerce_datetime_filter_value(value: float | bool | str) -> datetime:
    if not isinstance(value, str):
        raise InvalidAccountFilter("Date filters require ISO-8601 values.")
    parsed_datetime = parse_datetime(value)
    if parsed_datetime is None:
        parsed_date = parse_date(value)
        if parsed_date is None:
            raise InvalidAccountFilter("Date filters require ISO-8601 values.")
        parsed_datetime = datetime.combine(parsed_date, time.min, tzinfo=UTC)
    elif timezone.is_naive(parsed_datetime):
        parsed_datetime = timezone.make_aware(parsed_datetime, UTC)
    return parsed_datetime


def _apply_account_field_filter(
    queryset: QuerySet[Account], filter_: contracts.AccountTableFieldFilter
) -> QuerySet[Account]:
    field = filter_.field
    operator = filter_.operator
    values = filter_.values
    field_lookup = ACCOUNT_DIRECT_FIELDS.get(field)
    if field_lookup is None:
        field_lookup = f"_account_filter_{field.value}"
        queryset = queryset.annotate(**{field_lookup: KeyTextTransform(field.value, "_properties")})

    if operator == contracts.AccountTableFieldOperator.IS_SET:
        return queryset.filter(**{f"{field_lookup}__isnull": False})  # nosemgrep: orm-field-injection -- enum allowlist
    if operator == contracts.AccountTableFieldOperator.IS_NOT_SET:
        return queryset.filter(**{f"{field_lookup}__isnull": True})  # nosemgrep: orm-field-injection -- enum allowlist
    if not values:
        raise InvalidAccountFilter("Account field filters require at least one value.")

    if field in ACCOUNT_TEXT_FIELDS:
        if operator == contracts.AccountTableFieldOperator.EXACT:
            return queryset.filter(  # nosemgrep: orm-field-injection -- enum allowlist
                **{f"{field_lookup}__in": values}  # nosemgrep: orm-field-injection -- enum allowlist
            )
        if operator == contracts.AccountTableFieldOperator.IS_NOT:
            return queryset.filter(  # nosemgrep: orm-field-injection -- enum allowlist
                Q(**{f"{field_lookup}__isnull": True})  # nosemgrep: orm-field-injection -- enum allowlist
                | ~Q(**{f"{field_lookup}__in": values})  # nosemgrep: orm-field-injection -- enum allowlist
            )
        if operator in {
            contracts.AccountTableFieldOperator.CONTAINS,
            contracts.AccountTableFieldOperator.DOES_NOT_CONTAIN,
        }:
            predicate = Q()
            for value in values:
                predicate |= Q(  # nosemgrep: orm-field-injection -- enum allowlist
                    **{f"{field_lookup}__icontains": value}  # nosemgrep: orm-field-injection -- enum allowlist
                )
            if operator == contracts.AccountTableFieldOperator.DOES_NOT_CONTAIN:
                return queryset.filter(  # nosemgrep: orm-field-injection -- enum allowlist
                    Q(**{f"{field_lookup}__isnull": True})  # nosemgrep: orm-field-injection -- enum allowlist
                    | ~predicate
                )
            return queryset.filter(predicate)
        raise InvalidAccountFilter(f"Operator {operator.value} does not support text account fields.")

    if field in ACCOUNT_DATETIME_FIELDS:
        if len(values) != 1:
            raise InvalidAccountFilter("Date account field filters require one value.")
        target = _coerce_datetime_filter_value(values[0])
        if operator == contracts.AccountTableFieldOperator.DATE_EXACT:
            target_date = target.replace(hour=0, minute=0, second=0, microsecond=0)
            return queryset.filter(
                **{f"{field_lookup}__gte": target_date, f"{field_lookup}__lt": target_date + timedelta(days=1)}
            )
        lookup = {
            contracts.AccountTableFieldOperator.DATE_BEFORE: "lt",
            contracts.AccountTableFieldOperator.DATE_AFTER: "gt",
        }.get(operator)
        if lookup is None:
            raise InvalidAccountFilter(f"Operator {operator.value} does not support date account fields.")
        return queryset.filter(  # nosemgrep: orm-field-injection -- enum allowlists
            **{f"{field_lookup}__{lookup}": target}  # nosemgrep: orm-field-injection -- enum allowlists
        )

    raise InvalidAccountFilter(f"Unsupported account field: {field.value}")


def _coerce_custom_property_filter_values(
    filter_: contracts.AccountTableCustomPropertyFilter, display_type: DisplayType
) -> tuple[float | bool | str | datetime, ...]:
    data_type = DATA_TYPE_BY_DISPLAY_TYPE[display_type]
    values = filter_.values
    if filter_.operator in {
        contracts.AccountTableCustomPropertyOperator.IS_SET,
        contracts.AccountTableCustomPropertyOperator.IS_NOT_SET,
    }:
        return ()
    if not values:
        raise InvalidAccountFilter("Custom property filters require at least one value.")

    if data_type == DataType.NUMERIC:
        if any(isinstance(value, bool) for value in values):
            raise InvalidAccountFilter("Numeric custom property filters require numeric values.")
        try:
            return tuple(float(value) for value in values)
        except (TypeError, ValueError) as error:
            raise InvalidAccountFilter("Numeric custom property filters require numeric values.") from error
    if data_type == DataType.BOOLEAN:
        coerced: list[bool] = []
        for value in values:
            if isinstance(value, bool):
                coerced.append(value)
            elif str(value).lower() in {"true", "1"}:
                coerced.append(True)
            elif str(value).lower() in {"false", "0"}:
                coerced.append(False)
            else:
                raise InvalidAccountFilter("Boolean custom property filters require true or false values.")
        return tuple(coerced)
    if data_type == DataType.DATETIME:
        return tuple(_coerce_datetime_filter_value(value) for value in values)
    return tuple(str(value) for value in values)


def _custom_property_filter_predicate(
    filter_: contracts.AccountTableCustomPropertyFilter, display_type: DisplayType
) -> tuple[Q, bool]:
    operator = filter_.operator
    data_type = DATA_TYPE_BY_DISPLAY_TYPE[display_type]
    values = _coerce_custom_property_filter_values(filter_, display_type)
    value_field = {
        DataType.STRING: "value_str",
        DataType.NUMERIC: "value_num",
        DataType.BOOLEAN: "value_bool",
        DataType.DATETIME: "value_datetime",
    }[data_type]

    if operator == contracts.AccountTableCustomPropertyOperator.IS_SET:
        return Q(), False
    if operator == contracts.AccountTableCustomPropertyOperator.IS_NOT_SET:
        return Q(), True
    if operator in {
        contracts.AccountTableCustomPropertyOperator.EXACT,
        contracts.AccountTableCustomPropertyOperator.IS_NOT,
    }:
        return (  # nosemgrep: orm-field-injection -- data-type allowlist
            Q(**{f"{value_field}__in": values}),  # nosemgrep: orm-field-injection -- data-type allowlist
            operator == contracts.AccountTableCustomPropertyOperator.IS_NOT,
        )
    if operator in {
        contracts.AccountTableCustomPropertyOperator.REGEX,
        contracts.AccountTableCustomPropertyOperator.NOT_REGEX,
    }:
        raise InvalidAccountFilter("Regex custom property filters are not supported by account queries.")
    if operator in {
        contracts.AccountTableCustomPropertyOperator.CONTAINS,
        contracts.AccountTableCustomPropertyOperator.DOES_NOT_CONTAIN,
    }:
        if data_type != DataType.STRING:
            raise InvalidAccountFilter("Contains operators require a text custom property.")
        predicate = Q()
        for value in values:
            predicate |= Q(value_str__icontains=value)
        return predicate, operator == contracts.AccountTableCustomPropertyOperator.DOES_NOT_CONTAIN
    if operator in {
        contracts.AccountTableCustomPropertyOperator.GREATER_THAN,
        contracts.AccountTableCustomPropertyOperator.GREATER_THAN_OR_EQUAL,
        contracts.AccountTableCustomPropertyOperator.LESS_THAN,
        contracts.AccountTableCustomPropertyOperator.LESS_THAN_OR_EQUAL,
    }:
        if data_type != DataType.NUMERIC:
            raise InvalidAccountFilter("Comparison operators require a numeric custom property.")
        if len(values) != 1:
            raise InvalidAccountFilter("Numeric comparison filters require one value.")
        lookup = {
            contracts.AccountTableCustomPropertyOperator.GREATER_THAN: "gt",
            contracts.AccountTableCustomPropertyOperator.GREATER_THAN_OR_EQUAL: "gte",
            contracts.AccountTableCustomPropertyOperator.LESS_THAN: "lt",
            contracts.AccountTableCustomPropertyOperator.LESS_THAN_OR_EQUAL: "lte",
        }[operator]
        return Q(**{f"value_num__{lookup}": values[0]}), False  # nosemgrep: orm-field-injection -- operator allowlist
    if operator in {
        contracts.AccountTableCustomPropertyOperator.DATE_EXACT,
        contracts.AccountTableCustomPropertyOperator.DATE_BEFORE,
        contracts.AccountTableCustomPropertyOperator.DATE_AFTER,
    }:
        if data_type != DataType.DATETIME:
            raise InvalidAccountFilter("Date operators require a date or datetime custom property.")
        if len(values) != 1:
            raise InvalidAccountFilter("Date comparison filters require one value.")
        if operator == contracts.AccountTableCustomPropertyOperator.DATE_EXACT:
            target_date = cast(datetime, values[0]).replace(hour=0, minute=0, second=0, microsecond=0)
            return Q(value_datetime__gte=target_date, value_datetime__lt=target_date + timedelta(days=1)), False
        lookup = {
            contracts.AccountTableCustomPropertyOperator.DATE_BEFORE: "lt",
            contracts.AccountTableCustomPropertyOperator.DATE_AFTER: "gt",
        }[operator]
        return Q(  # nosemgrep: orm-field-injection -- operator allowlist
            **{f"value_datetime__{lookup}": values[0]}  # nosemgrep: orm-field-injection -- operator allowlist
        ), False
    raise InvalidAccountFilter(f"Unsupported custom property filter operator: {operator.value}")


def apply_account_filters(
    queryset: QuerySet[Account],
    *,
    team_id: int,
    filters: tuple[contracts.AccountTableFilter, ...],
    custom_property_display_types: dict[UUID, DisplayType],
) -> QuerySet[Account]:
    active_relationships = AccountRelationship.objects.for_team(team_id).filter(
        account_id=OuterRef("pk"), ended_at__isnull=True, user_id__isnull=False
    )
    for filter_ in filters:
        if isinstance(filter_, contracts.AccountTableSearchFilter):
            query = filter_.query.strip()
            if query:
                queryset = queryset.filter(Q(name__icontains=query) | Q(external_id__icontains=query))
        elif isinstance(filter_, contracts.AccountTableTagsFilter):
            if filter_.tag_names:
                matching_tags = TaggedItem.objects.filter(
                    account_id=OuterRef("pk"), tag__team_id=team_id, tag__name__in=filter_.tag_names
                )
                queryset = queryset.filter(Exists(matching_tags))
        elif isinstance(filter_, contracts.AccountTableAssignedToFilter):
            if filter_.user_ids:
                queryset = queryset.filter(Exists(active_relationships.filter(user_id__in=filter_.user_ids)))
        elif isinstance(filter_, contracts.AccountTableUnassignedFilter):
            queryset = queryset.filter(~Exists(active_relationships))
        elif isinstance(filter_, contracts.AccountTableAccountIdFilter):
            queryset = queryset.filter(id=filter_.account_id)
        elif isinstance(filter_, contracts.AccountTableFieldFilter):
            queryset = _apply_account_field_filter(queryset, filter_)
        elif isinstance(filter_, contracts.AccountTableCustomPropertyFilter):
            active_values = CustomPropertyValue.objects.for_team(team_id).filter(
                account_id=OuterRef("pk"), definition_id=filter_.definition_id, is_deleted=False
            )
            predicate, negate_exists = _custom_property_filter_predicate(
                filter_, custom_property_display_types[filter_.definition_id]
            )
            matching_values = active_values.filter(predicate)
            queryset = queryset.filter(~Exists(matching_values) if negate_exists else Exists(matching_values))
    return queryset
