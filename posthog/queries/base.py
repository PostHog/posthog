import re
import hashlib
import datetime
from collections.abc import Callable
from typing import Any, Optional, TypeVar, Union, cast
from zoneinfo import ZoneInfo

from django.db.models import Exists, OuterRef, Q, Value

from dateutil import parser
from dateutil.relativedelta import relativedelta
from rest_framework.exceptions import ValidationError

from posthog.constants import PropertyOperatorType
from posthog.models.cohort import Cohort, CohortOrEmpty, CohortPeople
from posthog.models.filters.filter import Filter
from posthog.models.filters.path_filter import PathFilter
from posthog.models.property import Property, PropertyGroup
from posthog.models.property.property import OperatorType, ValueT
from posthog.models.team import Team
from posthog.queries.util import convert_to_datetime_aware
from posthog.utils import get_compare_period_dates, is_valid_regex

FilterType = TypeVar("FilterType", Filter, PathFilter)


def determine_compared_filter(filter: FilterType) -> FilterType:
    if not filter.date_to or not filter.date_from:
        raise ValidationError("You need date_from and date_to to compare")
    date_from, date_to = get_compare_period_dates(
        filter.date_from,
        filter.date_to,
        filter.date_from_delta_mapping,
        filter.date_to_delta_mapping,
        filter.interval,
    )

    return filter.shallow_clone({"date_from": date_from.isoformat(), "date_to": date_to.isoformat()})


def convert_to_comparison(trend_entities: list[dict[str, Any]], filter, label: str) -> list[dict[str, Any]]:
    for entity in trend_entities:
        labels = [
            "{} {}".format(filter.interval if filter.interval is not None else "day", i)
            for i in range(len(entity["labels"]))
        ]
        entity.update(
            {
                "labels": labels,
                "days": entity["days"],
                "label": entity["label"],
                "compare_label": label,
                "compare": True,
            }
        )
    return trend_entities


"""
    handle_compare takes an Entity, Filter and a callable.
    It'll automatically create a new entity with the 'current' and 'previous' labels and automatically pick the right date_from and date_to filters .
    It will then call func(entity, filter, team_id).
"""


def handle_compare(filter, func: Callable, team: Team, **kwargs) -> list:
    all_entities = []
    base_entitites = func(filter=filter, team=team, **kwargs)
    if filter.compare:
        base_entitites = convert_to_comparison(base_entitites, filter, "current")
        all_entities.extend(base_entitites)

        compared_filter = determine_compared_filter(filter)
        comparison_entities = func(filter=compared_filter, team=team, **kwargs)
        comparison_entities = convert_to_comparison(comparison_entities, compared_filter, "previous")
        all_entities.extend(comparison_entities)
    else:
        all_entities.extend(base_entitites)
    return all_entities


def match_property(property: Property, override_property_values: dict[str, Any]) -> bool:
    # only looks for matches where key exists in override_property_values
    # doesn't support operator is_not_set

    if property.key not in override_property_values:
        raise ValidationError("can't match properties without an override value")

    key = property.key
    operator = property.operator or "exact"
    value = property.value
    override_value = override_property_values[key]

    if operator in ("exact", "is_not"):

        def compute_exact_match(value: ValueT, override_value: Any) -> bool:
            parsed_value = property._parse_value(value)
            if is_truthy_or_falsy_property_value(parsed_value):
                # Do boolean handling, such that passing in "true" or "True" or "false" or "False" as override value is equivalent
                truthy = parsed_value in (True, [True], "true", ["true"], "True", ["True"])
                return str(override_value).lower() == str(truthy).lower()

            if isinstance(value, list):
                return str(override_value).lower() in [str(val).lower() for val in value]
            return str(value).lower() == str(override_value).lower()

        if operator == "exact":
            return compute_exact_match(value, override_value)
        else:
            return not compute_exact_match(value, override_value)

    if operator == "is_set":
        return key in override_property_values

    if operator == "is_not_set":
        if key in override_property_values:
            return False
        raise ValidationError("can't match properties with operator is_not_set")

    if operator == "icontains":
        return str(value).lower() in str(override_value).lower()

    if operator == "not_icontains":
        return str(value).lower() not in str(override_value).lower()

    if operator in ("regex", "not_regex"):
        pattern = sanitize_regex_pattern(str(value))
        try:
            # Make the pattern more flexible by using DOTALL flag to allow . to match newlines
            # Added IGNORECASE for more flexibility
            compiled_pattern = re.compile(pattern, re.DOTALL | re.IGNORECASE)
            match = compiled_pattern.search(str(override_value))

            if operator == "regex":
                return match is not None
            else:
                return match is None

        except re.error:
            return False

    if operator in ("gt", "gte", "lt", "lte"):
        # :TRICKY: We adjust comparison based on the override value passed in,
        # to make sure we handle both numeric and string comparisons appropriately.
        def compare(lhs, rhs, operator):
            if operator == "gt":
                return lhs > rhs
            elif operator == "gte":
                return lhs >= rhs
            elif operator == "lt":
                return lhs < rhs
            elif operator == "lte":
                return lhs <= rhs
            else:
                raise ValueError(f"Invalid operator: {operator}")

        parsed_value = None
        try:
            parsed_value = float(value)  # type: ignore
        except Exception:
            pass

        if parsed_value is not None and override_value is not None:
            if isinstance(override_value, str):
                return compare(override_value, str(value), operator)
            else:
                return compare(override_value, parsed_value, operator)
        else:
            return compare(str(override_value), str(value), operator)

    if operator in ["is_date_before", "is_date_after", "is_date_exact"]:
        parsed_date = determine_parsed_date_for_property_matching(value)

        if not parsed_date:
            return False

        parsed_override_date = determine_parsed_incoming_date(override_value)

        if not parsed_override_date:
            return False

        if operator == "is_date_before":
            return parsed_override_date < parsed_date
        elif operator == "is_date_after":
            return parsed_override_date > parsed_date
        elif operator == "is_date_exact":
            return parsed_override_date == parsed_date

    return False


def determine_parsed_incoming_date(
    value: ValueT | datetime.date | datetime.datetime | float,
) -> datetime.datetime | None:
    # This parses the incoming date value. The range of possibilities is only limited by our customers imagination, but usually
    # take the form of a string, a unix timestamp, or a datetime object.
    if isinstance(value, datetime.datetime):
        return convert_to_datetime_aware(value)

    if isinstance(value, datetime.date):
        return convert_to_datetime_aware(datetime.datetime.combine(value, datetime.time.min))

    if isinstance(value, int) or isinstance(value, float):
        return datetime.datetime.fromtimestamp(value, tz=ZoneInfo("UTC"))
    if isinstance(value, str):
        try:
            parsed = parser.parse(value)
            return convert_to_datetime_aware(parsed)
        except Exception:
            try:
                # This might be a Unix timestamp passed as a string in milliseconds
                parsed_date = float(value)
                return datetime.datetime.fromtimestamp(parsed_date, tz=ZoneInfo("UTC"))
            except Exception:
                try:
                    # This might be a Unix timestamp passed as a string in seconds
                    parsed_date = int(value)
                    return datetime.datetime.fromtimestamp(parsed_date, tz=ZoneInfo("UTC"))
                except Exception:
                    pass

    return None


def determine_parsed_date_for_property_matching(value: ValueT) -> datetime.datetime | None:
    # This parses the filter value we compare against. The range of possible values is limited by our UI.
    parsed_date = None
    try:
        parsed_date = relative_date_parse_for_feature_flag_matching(str(value))

        if not parsed_date:
            parsed_date = parser.parse(str(value))
            parsed_date = convert_to_datetime_aware(parsed_date)
    except Exception:
        return None

    return parsed_date


def empty_or_null_with_value_q(
    column: str,
    key: str,
    operator: Optional[OperatorType],
    value: ValueT,
    negated: bool = False,
) -> Q:
    if operator == "exact" or operator is None:
        value_as_given = Property._parse_value(value)
        value_as_coerced_to_number = Property._parse_value(value, convert_to_number=True)
        # TRICKY: Don't differentiate between 'true' and '"true"' when database matching (one is boolean, other is string)
        if is_truthy_or_falsy_property_value(value_as_given):
            truthy = value_as_given in (True, [True], "true", ["true"], "True", ["True"])
            target_filter = lookup_q(f"{column}__{key}", truthy) | lookup_q(f"{column}__{key}", str(truthy).lower())
        elif value_as_given == value_as_coerced_to_number:
            target_filter = lookup_q(f"{column}__{key}", value_as_given)
        else:
            target_filter = lookup_q(f"{column}__{key}", value_as_given) | lookup_q(
                f"{column}__{key}", value_as_coerced_to_number
            )
    else:
        parsed_value = None
        if operator in ("gt", "gte", "lt", "lte"):
            if isinstance(value, list):
                # If the value is a list for these operators,
                # we should not return any results, as we can't compare a list to a single value
                # TODO: should we try and parse each value in the list and return results based on that?
                return Q(pk__isnull=True)

            # At this point, we know that the value is not a list, so we can safely parse it
            # There might still be exceptions, but we're catching them below
            try:
                parsed_value = float(value)
            except Exception:
                pass

        if parsed_value is not None:
            # When we can coerce given value to a number, check whether the value in DB is a number
            # and do a numeric comparison. Otherwise, do a string comparison.
            sanitized_key = sanitize_property_key(key)
            target_filter = Q(
                Q(**{f"{column}__{key}__{operator}": str(value), f"{column}_{sanitized_key}_type": Value("string")})
                | Q(**{f"{column}__{key}__{operator}": parsed_value, f"{column}_{sanitized_key}_type": Value("number")})
            )
        else:
            target_filter = Q(**{f"{column}__{key}__{operator}": value})

    query_filter = Q(target_filter & Q(**{f"{column}__has_key": key}) & ~Q(**{f"{column}__{key}": None}))

    if negated:
        return ~query_filter
    return query_filter


def lookup_q(key: str, value: Any) -> Q:
    # exact and is_not operators can pass lists as arguments. Handle those lookups!
    if isinstance(value, list):
        return Q(**{f"{key}__in": value})
    return Q(**{key: value})


def property_to_Q(
    project_id: int,
    property: Property,
    override_property_values: Optional[dict[str, Any]] = None,
    cohorts_cache: Optional[dict[int, CohortOrEmpty]] = None,
    using_database: str = "default",
) -> Q:
    if override_property_values is None:
        override_property_values = {}
    if property.type not in ["person", "group", "cohort", "event", "flag"]:
        # We need to support event type for backwards compatibility, even though it's treated as a person property type
        # Note: "flag" type is not supported here as flag dependencies are handled at the API layer during validation
        raise ValueError(f"property_to_Q: type is not supported: {repr(property.type)}")

    value = property._parse_value(property.value)
    if property.type == "cohort":
        cohort_id = int(cast(Union[str, int], value))
        if cohorts_cache is not None:
            if cohorts_cache.get(cohort_id) is None:
                queried_cohort = (
                    Cohort.objects.db_manager(using_database)
                    .filter(pk=cohort_id, team__project_id=project_id, deleted=False)
                    .first()
                )
                cohorts_cache[cohort_id] = queried_cohort or ""

            cohort = cohorts_cache[cohort_id]
        else:
            cohort = (
                Cohort.objects.db_manager(using_database)
                .filter(pk=cohort_id, team__project_id=project_id, deleted=False)
                .first()
            )

        if not cohort:
            # Don't match anything if cohort doesn't exist
            return Q(pk__isnull=True)

        if cohort.is_static:
            return Q(
                Exists(
                    CohortPeople.objects.db_manager(using_database)
                    .filter(
                        cohort_id=cohort_id,
                        person_id=OuterRef("id"),
                        cohort__id=cohort_id,
                    )
                    .only("id")
                )
            )
        else:
            # :TRICKY: This has potential to create an infinite loop if the cohort is recursive.
            # But, this shouldn't happen because we check for cyclic cohorts on creation.
            return property_group_to_Q(
                project_id,
                cohort.properties,
                override_property_values,
                cohorts_cache,
                using_database,
            )

    # short circuit query if key exists in override_property_values
    if property.key in override_property_values:
        # if match found, add an explicit match-all Q object
        # if not found, return falsy Q
        if not match_property(property, override_property_values):
            return Q(pk__isnull=True)
        else:
            # TRICKY: We need to return an explicit match-all Q object, instead of an empty Q object,
            # because the empty Q object,  when OR'ed with other Q objects, results in removing the empty Q object.
            # This isn't what we want here, because this is an explicit true match, which when OR'ed with others,
            # should not be removed, and return True.
            # See https://code.djangoproject.com/ticket/32554 for gotcha explanation
            return Q(pk__isnull=False)

    # if no override matches, return a true Q object

    column = "group_properties" if property.type == "group" else "properties"

    if property.operator == "is_set":
        return Q(**{f"{column}__{property.key}__isnull": False})
    if property.operator == "is_not_set":
        return Q(**{f"{column}__{property.key}__isnull": True})
    if property.operator in ("regex", "not_regex") and not is_valid_regex(str(value)):
        # Return no data for invalid regexes
        return Q(pk=-1)
    if isinstance(property.operator, str) and property.operator.startswith("not_"):
        return empty_or_null_with_value_q(
            column,
            property.key,
            cast(OperatorType, property.operator[4:]),
            value,
            negated=True,
        )

    if property.operator in ("is_date_after", "is_date_before"):
        effective_operator = "gt" if property.operator == "is_date_after" else "lt"
        effective_value = value

        # First try relative date parsing
        relative_date = relative_date_parse_for_feature_flag_matching(str(value))
        if relative_date:
            effective_value = relative_date.isoformat()
        else:
            # Parse the date string and convert to ISO format for consistent comparison
            # This ensures we're comparing dates in the same format (ISO 8601)
            parsed_date = determine_parsed_date_for_property_matching(value)
            if parsed_date:
                effective_value = parsed_date.isoformat()

        return Q(**{f"{column}__{property.key}__{effective_operator}": effective_value})

    if property.operator == "is_not":
        # is_not is inverse of exact
        return empty_or_null_with_value_q(column, property.key, "exact", value, negated=True)

    # NOTE: existence clause necessary when overall clause is negated
    return empty_or_null_with_value_q(column, property.key, property.operator, property.value)


def property_group_to_Q(
    project_id: int,
    property_group: PropertyGroup,
    override_property_values: Optional[dict[str, Any]] = None,
    cohorts_cache: Optional[dict[int, CohortOrEmpty]] = None,
    using_database: str = "default",
) -> Q:
    if override_property_values is None:
        override_property_values = {}
    filters = Q()

    if not property_group or len(property_group.values) == 0:
        return filters

    if isinstance(property_group.values[0], PropertyGroup):
        for group in property_group.values:
            group_filter = property_group_to_Q(
                project_id,
                cast(PropertyGroup, group),
                override_property_values,
                cohorts_cache,
                using_database,
            )
            if property_group.type == PropertyOperatorType.OR:
                filters |= group_filter
            else:
                filters &= group_filter
    else:
        for property in property_group.values:
            property = cast(Property, property)
            property_filter = property_to_Q(
                project_id, property, override_property_values, cohorts_cache, using_database
            )
            if property_group.type == PropertyOperatorType.OR:
                if property.negation:
                    filters |= ~property_filter
                else:
                    filters |= property_filter
            else:
                if property.negation:
                    filters &= ~property_filter
                else:
                    filters &= property_filter

    return filters


def properties_to_Q(
    project_id: int,
    properties: list[Property],
    override_property_values: Optional[dict[str, Any]] = None,
    cohorts_cache: Optional[dict[int, CohortOrEmpty]] = None,
    using_database: str = "default",
) -> Q:
    """
    Converts a filter to Q, for use in Django ORM .filter()
    If you're filtering a Person/Group QuerySet, use is_direct_query to avoid doing an unnecessary nested loop
    """
    if override_property_values is None:
        override_property_values = {}
    filters = Q()

    if len(properties) == 0:
        return filters

    return property_group_to_Q(
        project_id,
        PropertyGroup(type=PropertyOperatorType.AND, values=properties),
        override_property_values,
        cohorts_cache,
        using_database,
    )


def is_truthy_or_falsy_property_value(value: Any) -> bool:
    # Does not resolve 0 and 1 as true, but does resolve the strings as true
    return (
        value in ("true", ["true"], [True], [False], "false", ["false"], "True", ["True"], "False", ["False"])
        or value is True
        or value is False
    )


# Note: Any changes to this function need to be reflected in the rust version
# rust/feature-flags/src/properties/relative_date.rs
def relative_date_parse_for_feature_flag_matching(value: str) -> Optional[datetime.datetime]:
    regex = r"^-?(?P<number>[0-9]+)(?P<interval>[a-z])$"
    match = re.search(regex, value)
    parsed_dt = datetime.datetime.now(tz=ZoneInfo("UTC"))
    if match:
        number = int(match.group("number"))

        if number >= 10_000:
            # Guard against overflow, disallow numbers greater than 10_000
            return None

        interval = match.group("interval")
        if interval == "h":
            parsed_dt = parsed_dt - relativedelta(hours=number)
        elif interval == "d":
            parsed_dt = parsed_dt - relativedelta(days=number)
        elif interval == "w":
            parsed_dt = parsed_dt - relativedelta(weeks=number)
        elif interval == "m":
            parsed_dt = parsed_dt - relativedelta(months=number)
        elif interval == "y":
            parsed_dt = parsed_dt - relativedelta(years=number)
        else:
            return None

        return parsed_dt
    else:
        return None


def sanitize_property_key(key: Any) -> str:
    string_key = str(key)
    # remove all but a-zA-Z0-9 characters from the key
    substitute = re.sub(r"[^a-zA-Z0-9]", "", string_key)

    # :TRICKY: We also want to prevent clashes between key1_ and key1, or key1 and key2 so we add
    #  a salt based on hash of the key
    # This is because we don't want to overwrite the value of key1 when we're trying to read key2
    hash_value = hashlib.sha1(string_key.encode("utf-8")).hexdigest()[:15]
    return f"{substitute}_{hash_value}"


def sanitize_regex_pattern(pattern: str) -> str:
    # If it doesn't look like a property match pattern, return it as-is
    if not ('"' in pattern or "'" in pattern or ":" in pattern):
        return pattern

    # First, temporarily replace escaped quotes with markers
    pattern = pattern.replace(r"\"", "__ESCAPED_DOUBLE_QUOTE__")
    pattern = pattern.replace(r"\'", "__ESCAPED_SINGLE_QUOTE__")

    # Replace unescaped quotes with a pattern that matches either quote type
    pattern = pattern.replace('"', "['\"]")

    # Add optional whitespace around colons to handle Python dict format
    pattern = pattern.replace(":", r"\s*:\s*")

    # Now restore the escaped quotes, but convert them to also match either quote type
    pattern = pattern.replace("__ESCAPED_DOUBLE_QUOTE__", "['\"]")
    pattern = pattern.replace("__ESCAPED_SINGLE_QUOTE__", "['\"]")

    # If the pattern looks like a property match (key:value), convert it to use lookaheads
    if "['\"]" in pattern:
        # Split the pattern if it's trying to match multiple properties
        parts = pattern.split("[^}]*")
        converted_parts = []
        for part in parts:
            if "['\"]" in part:
                # Extract the key and value from patterns like ['"]key['"]\s*:\s*['"]value['"]
                try:
                    # Use a non-capturing group for quotes and match the exact key name
                    # This ensures we don't match partial keys or keys that are substrings of others
                    key = re.search(r'\[\'"\]((?:[^\'"\s:}]+))\[\'"\]\\s\*:\\s\*\[\'"\](.*?)\[\'"\]', part)
                    if key:
                        key_name, value = key.groups()
                        # Escape special regex characters in the key name
                        escaped_key_name = re.escape(key_name)
                        # Convert to a positive lookahead that matches the exact key-value pair
                        converted = f"(?=.*['\"]?{escaped_key_name}['\"]?\\s*:\\s*['\"]?{value}['\"]?)"
                        converted_parts.append(converted)
                except Exception:
                    # If we can't parse it, use the original pattern
                    converted_parts.append(part)
            else:
                converted_parts.append(part)
        pattern = "".join(converted_parts)

    return pattern
