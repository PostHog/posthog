import json
from typing import TYPE_CHECKING, Any, Optional, Union, cast

import posthoganalytics
from rest_framework.exceptions import ValidationError

from posthog.constants import FILTER_TEST_ACCOUNTS, PROPERTIES, PropertyOperatorType
from posthog.exceptions_capture import capture_exception
from posthog.schema_enums import PropertyOperator

from .property import Property, PropertyGroup, PropertyValidationError

if TYPE_CHECKING:
    from posthog.models.team import Team


def parse_property_group_data(data: Any) -> PropertyGroup:
    """Parse a `properties` value into a PropertyGroup, in any shape the API has ever accepted."""
    if isinstance(data, str):
        # `?properties=` reaches here as an empty string once the request dict is passed straight
        # through. The filter layer that used to sit in front dropped a falsy query param before
        # parsing, so an empty value has to keep meaning "no properties" instead of failing.
        if not data.strip():
            return PropertyGroup(type=PropertyOperatorType.AND, values=[])
        try:
            loaded_props = json.loads(data)
        except json.decoder.JSONDecodeError:
            raise ValidationError("Data is unparsable!")
    else:
        loaded_props = data

    if isinstance(loaded_props, dict) and "type" in loaded_props and "values" in loaded_props:
        try:
            return parse_property_group(loaded_props)
        except ValidationError:
            raise
        except ValueError as e:
            raise ValidationError(f"PropertyGroup is unparsable: {e}")
    elif isinstance(loaded_props, PropertyGroup):
        return loaded_props

    return PropertyGroup(type=PropertyOperatorType.AND, values=parse_properties(loaded_props))


def parse_properties(properties: Optional[Any]) -> list[Property]:
    if isinstance(properties, list):
        _properties = []
        for prop_params in properties:
            if isinstance(prop_params, Property):
                _properties.append(prop_params)
            else:
                try:
                    new_prop = Property(**prop_params)
                    _properties.append(new_prop)
                except (PropertyValidationError, ValidationError, TypeError) as e:
                    # PropertyValidationError covers every failure Property.__init__ itself
                    # raises; ValidationError covers validate_group_type_index's own DRF
                    # error, which Property.__init__ leaves unwrapped so it still reaches
                    # direct callers as a 400; TypeError covers `Property(**prop_params)`
                    # failing to unpack prop_params as a mapping before __init__ even runs.
                    # Dropping an unparsable property changes validation behavior for every
                    # caller (e.g. cohort.properties.flat missing a behavioral leaf lets
                    # behavioral-cohort checks pass silently), so this must stay visible
                    # instead of failing silent. Report structure only — never the
                    # property's own value/event_filters — since those can carry real user
                    # data (e.g. an exact-match email filter). Code-variable capture would
                    # otherwise attach those same values from this frame's locals regardless
                    # of what we pass as additional_properties, so it's disabled for this call.
                    prop_dict = prop_params if isinstance(prop_params, dict) else {}
                    with posthoganalytics.new_context():
                        posthoganalytics.set_capture_exception_code_variables_context(False)
                        capture_exception(
                            e,
                            additional_properties={
                                "property_type": prop_dict.get("type"),
                                "property_fields": sorted(prop_dict.keys()) or None,
                            },
                        )
                    continue
        return _properties
    if not properties:
        return []

    # old style dict properties
    ret = []
    for key, value in properties.items():
        key_split = key.split("__")
        ret.append(
            Property(
                key=key_split[0],
                value=value,
                operator=key_split[1] if len(key_split) > 1 else None,
                type="event",
            )
        )
    return ret


def parse_property_group(group: Optional[dict]) -> PropertyGroup:
    if group and "type" in group and "values" in group:
        return PropertyGroup(
            PropertyOperatorType(group["type"].upper()),
            parse_property_group_list(group["values"]),
        )

    return PropertyGroup(PropertyOperatorType.AND, cast(list[Property], []))


def parse_property_group_list(prop_list: Optional[list]) -> Union[list[Property], list[PropertyGroup]]:
    if not prop_list:
        # empty prop list
        return cast(list[Property], [])
    has_property_groups = False
    has_simple_properties = False

    for prop in prop_list:
        if "type" in prop and "values" in prop:
            has_property_groups = True
        elif "key" in prop:
            has_simple_properties = True
        else:
            has_property_groups = True

    if has_simple_properties and has_property_groups:
        raise ValidationError("Property list cannot contain both PropertyGroup and Property objects")

    if has_property_groups:
        return [parse_property_group(group) for group in prop_list]
    else:
        return parse_properties(prop_list)


def expand_cohort_properties(prop_group: PropertyGroup, team: "Team") -> PropertyGroup:
    """Replace cohort properties with the concrete lookups they stand for.

    A cohort that is not static, precalculated, or behavioral expands into its own
    person properties, so it matches before its first calculation has run.
    """
    from .util import clear_excess_levels  # noqa: PLC0415 — avoids a circular import

    return clear_excess_levels(expand_cohort_group(prop_group, team), skip=True)


def expand_cohort_group(prop_group: PropertyGroup, team: "Team") -> PropertyGroup:
    new_values: list[Any] = []
    for value in prop_group.values:
        if isinstance(value, PropertyGroup):
            new_values.append(expand_cohort_group(value, team))
        elif isinstance(value, Property):
            new_values.append(expand_cohort_property(value, team))

    prop_group.values = new_values
    return prop_group


def expand_cohort_property(property: Property, team: "Team") -> PropertyGroup:
    if property.type != "cohort":
        # PropertyOperatorType doesn't really matter here, since only one value.
        return PropertyGroup(type=PropertyOperatorType.AND, values=[property])

    from products.cohorts.backend.models.cohort import Cohort  # noqa: PLC0415 — avoids a circular import
    from products.cohorts.backend.models.util import simplified_cohort_filter_properties  # noqa: PLC0415

    try:
        cohort = Cohort.objects.get(pk=cast(str | int, property.value), team__project_id=team.project_id)
    except Cohort.DoesNotExist:
        # :TODO: Handle non-existing resource in-query instead
        return PropertyGroup(type=PropertyOperatorType.AND, values=[property])

    return simplified_cohort_filter_properties(
        cohort, team, property.negation or property.operator == PropertyOperator.NOT_IN.value
    )


def parse_properties_for_team(data: dict, team: "Team") -> PropertyGroup:
    """Parse a filter dict's properties and resolve them against the team.

    Folds in the team's test-account filters when the dict asks for them, then expands
    cohorts, matching what a team-bound filter used to produce.
    """
    parsed = parse_property_group_data(data.get(PROPERTIES))

    if data.get(FILTER_TEST_ACCOUNTS) in (True, "true"):
        test_accounts = {"type": "AND", "values": team.test_account_filters}
        existing = parsed.to_dict()
        parsed = parse_property_group_data(
            {"type": "AND", "values": [test_accounts, existing]} if existing else test_accounts
        )

    return expand_cohort_properties(parsed, team)
