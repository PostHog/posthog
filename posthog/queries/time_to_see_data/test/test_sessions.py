import pytest


@pytest.mark.parametrize(
    "query,expected_condition",
    [
        ({}, "1 = 1"),
        (
            {"team_id": 4},
            "metrics_time_to_see_data.team_id = %(team_id)s",
        ),
        (
            {"team_id": 4, "session_id": "456"},
            "metrics_time_to_see_data.team_id = %(team_id)s AND metrics_time_to_see_data.session_id = %(session_id)s",
        ),
    ],
)
def test_sessions_condition(query, expected_condition):
    from posthog.queries.time_to_see_data.serializers import SessionsQuerySerializer
    from posthog.queries.time_to_see_data.sessions import _sessions_condition

    serializer = SessionsQuerySerializer(data=query)
    serializer.is_valid(raise_exception=True)

    assert _sessions_condition(serializer) == (expected_condition, query)
