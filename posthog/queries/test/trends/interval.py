from posthog.queries.test.trends.base import QueryTest

_events = {
    "events": [
        {"event": "sign up", "distinct_id": "person1", "timestamp": "2020-01-01T00:00:00Z"},
        {"event": "sign up", "distinct_id": "person1", "timestamp": "2020-01-02T00:00:00Z"},
        {"event": "sign up", "distinct_id": "person1", "timestamp": "2020-01-03T00:00:00Z"},
    ],
    "people": [{"distinct_ids": ["person1"], "properties": {"$some_prop": "some_val"}},],
}

_minute_test = QueryTest(
    name="minute interval",
    data=_events,
    filter_data={
        "date_from": "2020-01-01T00:00:00Z",
        "date_to": "2020-01-03T00:00:00Z",
        "interval": "minute",
        "events": [{"id": "sign up"}],
    },
    result=[
        {
            "action": {
                "id": "sign up",
                "type": "events",
                "order": None,
                "name": "sign up",
                "math": None,
                "math_property": None,
                "properties": [],
            },
            "label": "sign up",
            "count": 3,
            "data": [1, 1, 1],
            "labels": ["Wed. 1 January", "Thu. 2 January", "Fri. 3 January"],
            "days": ["2020-01-01", "2020-01-02", "2020-01-03"],
        }
    ],
)

_hour_test = QueryTest(
    name="hour interval",
    data=_events,
    filter_data={
        "date_from": "2020-01-01T00:00:00Z",
        "date_to": "2020-01-03T00:00:00Z",
        "interval": "hour",
        "events": [{"id": "sign up"}],
    },
    result=[
        {
            "action": {
                "id": "sign up",
                "type": "events",
                "order": None,
                "name": "sign up",
                "math": None,
                "math_property": None,
                "properties": [],
            },
            "label": "sign up",
            "count": 3,
            "data": [1, 1, 1],
            "labels": ["Wed. 1 January", "Thu. 2 January", "Fri. 3 January"],
            "days": ["2020-01-01", "2020-01-02", "2020-01-03"],
        }
    ],
)

_day_test = QueryTest(
    name="day interval",
    data=_events,
    filter_data={
        "date_from": "2020-01-01T00:00:00Z",
        "date_to": "2020-01-03T00:00:00Z",
        "interval": "day",
        "events": [{"id": "sign up"}],
    },
    result=[
        {
            "action": {
                "id": "sign up",
                "type": "events",
                "order": None,
                "name": "sign up",
                "math": None,
                "math_property": None,
                "properties": [],
            },
            "label": "sign up",
            "count": 3,
            "data": [1, 1, 1],
            "labels": ["Wed. 1 January", "Thu. 2 January", "Fri. 3 January"],
            "days": ["2020-01-01", "2020-01-02", "2020-01-03"],
        }
    ],
)

_week_test = QueryTest(
    name="week interval",
    data=_events,
    filter_data={
        "date_from": "2020-01-01T00:00:00Z",
        "date_to": "2020-01-03T00:00:00Z",
        "interval": "week",
        "events": [{"id": "sign up"}],
    },
    result=[
        {
            "action": {
                "id": "sign up",
                "type": "events",
                "order": None,
                "name": "sign up",
                "math": None,
                "math_property": None,
                "properties": [],
            },
            "label": "sign up",
            "count": 3,
            "data": [1, 1, 1],
            "labels": ["Wed. 1 January", "Thu. 2 January", "Fri. 3 January"],
            "days": ["2020-01-01", "2020-01-02", "2020-01-03"],
        }
    ],
)

_month_test = QueryTest(
    name="month interval",
    data=_events,
    filter_data={
        "date_from": "2020-01-01T00:00:00Z",
        "date_to": "2020-01-03T00:00:00Z",
        "interval": "month",
        "events": [{"id": "sign up"}],
    },
    result=[
        {
            "action": {
                "id": "sign up",
                "type": "events",
                "order": None,
                "name": "sign up",
                "math": None,
                "math_property": None,
                "properties": [],
            },
            "label": "sign up",
            "count": 3,
            "data": [1, 1, 1],
            "labels": ["Wed. 1 January", "Thu. 2 January", "Fri. 3 January"],
            "days": ["2020-01-01", "2020-01-02", "2020-01-03"],
        }
    ],
)


interval_test = [_minute_test, _hour_test, _day_test, _week_test, _month_test]
