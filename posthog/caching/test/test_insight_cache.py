from datetime import timedelta
from typing import Optional, cast
from unittest.mock import call, patch

import pytest
from django.utils.timezone import now

from posthog.caching.insight_cache import fetch_states_in_need_of_updating, schedule_cache_updates
from posthog.caching.insight_caching_state import upsert
from posthog.caching.test.test_insight_caching_state import create_insight, filter_dict
from posthog.models import InsightCachingState, Team, User
from posthog.models.signals import mute_selected_signals


def create_insight_caching_state(
    team: Team,
    user: User,
    last_refresh: Optional[timedelta] = timedelta(days=14),  # noqa
    last_refresh_queued_at: Optional[timedelta] = None,  # noqa
    target_cache_age: Optional[timedelta] = timedelta(days=1),  # noqa
    refresh_attempt: int = 0,
    filters=filter_dict,
    **kw,
):
    with mute_selected_signals():
        insight = create_insight(team, user, filters=filters)

    model = cast(InsightCachingState, upsert(team, insight))
    model.last_refresh = now() - last_refresh if last_refresh is not None else None
    model.last_refresh_queued_at = now() - last_refresh_queued_at if last_refresh_queued_at is not None else None
    model.target_cache_age_seconds = target_cache_age.total_seconds() if target_cache_age is not None else None
    model.refresh_attempt = refresh_attempt
    model.save()
    return model


@pytest.mark.django_db
@patch("posthog.celery.update_cache_task")
def test_schedule_cache_updates(update_cache_task, team: Team, user: User):
    caching_state1 = create_insight_caching_state(team, user, filters=filter_dict, last_refresh=None)
    create_insight_caching_state(team, user, filters=filter_dict)
    caching_state3 = create_insight_caching_state(
        team,
        user,
        filters={
            **filter_dict,
            "events": [{"id": "$pageleave"}],
        },
    )

    schedule_cache_updates()

    assert update_cache_task.delay.call_args_list == [call(caching_state1.pk), call(caching_state3.pk)]

    last_refresh_queued_at = InsightCachingState.objects.filter(team=team).values_list(
        "last_refresh_queued_at", flat=True
    )
    assert len(last_refresh_queued_at) == 3
    assert None not in last_refresh_queued_at


@pytest.mark.parametrize(
    "params,expected_matches",
    [
        ({}, 1),
        ({"limit": 0}, 0),
        ({"last_refresh": None}, 1),
        ({"target_cache_age": None, "last_refresh": None}, 0),
        ({"target_cache_age": timedelta(days=1), "last_refresh": timedelta(days=2)}, 1),
        ({"target_cache_age": timedelta(days=1), "last_refresh": timedelta(hours=23)}, 0),
        ({"target_cache_age": timedelta(days=1), "last_refresh_queued_at": timedelta(hours=23)}, 1),
        ({"target_cache_age": timedelta(days=1), "last_refresh_queued_at": timedelta(minutes=5)}, 0),
        ({"refresh_attempt": 2}, 1),
        ({"refresh_attempt": 3}, 0),
    ],
)
@pytest.mark.django_db
def test_fetch_states_in_need_of_updating(team: Team, user: User, params, expected_matches):
    create_insight_caching_state(team, user, **params)

    results = fetch_states_in_need_of_updating(params.get("limit", 10))
    assert len(results) == expected_matches
