import pytest

from rest_framework.serializers import ValidationError

from products.cross_project_dashboards.backend.logic import validate_cross_project_filters


def test_dates_and_interval_are_allowed():
    validate_cross_project_filters({"date_from": "-7d", "date_to": None, "interval": "week"})


def test_string_keyed_property_filters_are_allowed():
    validate_cross_project_filters(
        {"properties": [{"type": "event", "key": "$browser", "operator": "exact", "value": "Chrome"}]}
    )


def test_empty_filters_are_allowed():
    validate_cross_project_filters(None)
    validate_cross_project_filters({})


@pytest.mark.parametrize(
    "property_filter",
    [
        {"type": "cohort", "key": "id", "value": 42},
        {"type": "group", "key": "name", "group_type_index": 0, "operator": "exact", "value": "a"},
        {"type": "flag", "key": "123", "operator": "flag_evaluates_to", "value": True},
        {"type": "data_warehouse", "key": "col", "operator": "exact", "value": "x"},
        {"type": "error_tracking_issue", "key": "id", "operator": "exact", "value": "x"},
        {"type": "hogql", "key": "1 = 1"},
    ],
)
def test_project_bound_property_filters_are_rejected(property_filter):
    with pytest.raises(ValidationError) as err:
        validate_cross_project_filters({"properties": [property_filter]})
    assert property_filter["type"] in str(err.value)


@pytest.mark.parametrize(
    "properties",
    [
        {"type": "AND", "values": [{"type": "hogql", "key": "1=1"}]},
        [{"type": "AND", "values": [{"type": "cohort", "key": "id", "value": 42}]}],
    ],
    ids=["group_dict", "nested_group_in_list"],
)
def test_project_bound_filters_inside_property_groups_are_rejected(properties):
    with pytest.raises(ValidationError):
        validate_cross_project_filters({"properties": properties})


def test_property_group_is_stored_as_the_flat_list_the_tiles_apply():
    leaf = {"type": "event", "key": "$browser", "operator": "exact", "value": "Chrome"}

    normalized = validate_cross_project_filters({"properties": {"type": "AND", "values": [leaf]}})

    assert normalized["properties"] == [leaf]


@pytest.mark.parametrize("filters", ["abc", 5, ["date_from"]])
def test_filters_that_are_not_an_object_are_a_validation_error(filters):
    with pytest.raises(ValidationError):
        validate_cross_project_filters(filters)


def test_cohort_breakdown_in_the_breakdowns_list_is_rejected():
    with pytest.raises(ValidationError):
        validate_cross_project_filters({"breakdown_filter": {"breakdowns": [{"type": "cohort", "property": 42}]}})


def test_cohort_breakdown_is_rejected():
    with pytest.raises(ValidationError):
        validate_cross_project_filters({"breakdown_filter": {"breakdown_type": "cohort", "breakdown": [42]}})


def test_group_breakdown_is_rejected():
    with pytest.raises(ValidationError):
        validate_cross_project_filters({"breakdown_filter": {"breakdown_group_type_index": 0}})


def test_event_breakdown_is_allowed():
    validate_cross_project_filters({"breakdown_filter": {"breakdown_type": "event", "breakdown": "$browser"}})
