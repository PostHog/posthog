from datetime import datetime

from posthog.helpers.item_history import HistoryListItem, compute_history
from posthog.mixins import pairwise
from posthog.models import HistoricalVersion


def test_pairwise():
    assert list(pairwise([1, 2, 3, 4, 5, 6, 7])) == [(1, 2), (2, 3), (3, 4), (4, 5), (5, 6), (6, 7), (7, None)]


def test_no_history_returns_an_empty_list():
    assert compute_history("anything", []) == []


def test_a_single_update_shows_updated_by_history_hog():
    an_update = HistoricalVersion(
        state={"key": "the-key"},
        name="FeatureFlag",
        action="not create",
        item_id=4,
        versioned_at=datetime.fromisoformat("2020-04-01T12:34:56"),
        team_id=1,
    )
    assert compute_history("FeatureFlag", [(an_update, None)]) == [
        HistoryListItem(
            email="history.hog@posthog.com",
            name="history hog",
            user_id=-1,
            action="history_hog_imported_FeatureFlag",
            detail={"id": 4, "key": "the-key"},
            created_at="2020-04-01T12:34:56",
        )
    ]


def test_possible_feature_flag_changes():
    # for a feature flag can change
    #  * key
    #  * name (which is description)
    #  * active
    #  * roll out percentage
    #  * deleted (for soft delete)
    #  * filters json
    # here's every one of those changes and each of the items the API will return for it
    versions = [
        HistoricalVersion(
            created_by_id=3,
            created_by_name="darth",
            created_by_email="darth.vader@posthog.com",
            state={
                "key": "the-new-key",
                "name": "a new description",
                "active": True,
                "rollout_percentage": 25,
                "deleted": True,
                "filters": {"some": "json", "and": "more"},
            },
            name="FeatureFlag",
            action="update",
            item_id=4,
            versioned_at=datetime.fromisoformat("2020-04-04T12:34:56"),
            team_id=1,
        ),
        HistoricalVersion(
            created_by_id=3,
            created_by_name="darth",
            created_by_email="darth.vader@posthog.com",
            state={
                "key": "the-new-key",
                "name": "a new description",
                "active": True,
                "rollout_percentage": 25,
                "deleted": True,
                "filters": {"some": "json"},
            },
            name="FeatureFlag",
            action="update",
            item_id=4,
            versioned_at=datetime.fromisoformat("2020-04-04T12:34:56"),
            team_id=1,
        ),
        HistoricalVersion(
            created_by_id=3,
            created_by_name="darth",
            created_by_email="darth.vader@posthog.com",
            state={
                "key": "the-new-key",
                "name": "a new description",
                "active": True,
                "rollout_percentage": 25,
                "deleted": True,
            },
            name="FeatureFlag",
            action="update",
            item_id=4,
            versioned_at=datetime.fromisoformat("2020-04-04T12:34:56"),
            team_id=1,
        ),
        HistoricalVersion(
            created_by_id=3,
            created_by_name="darth",
            created_by_email="darth.vader@posthog.com",
            state={"key": "the-new-key", "name": "a new description", "active": True, "rollout_percentage": 25},
            name="FeatureFlag",
            action="update",
            item_id=4,
            versioned_at=datetime.fromisoformat("2020-04-04T12:34:56"),
            team_id=1,
        ),
        HistoricalVersion(
            created_by_id=3,
            created_by_name="darth",
            created_by_email="darth.vader@posthog.com",
            state={"key": "the-new-key", "name": "a new description", "active": True, "rollout_percentage": 50},
            name="FeatureFlag",
            action="update",
            item_id=4,
            versioned_at=datetime.fromisoformat("2020-04-04T12:34:56"),
            team_id=1,
        ),
        HistoricalVersion(
            created_by_id=3,
            created_by_name="darth",
            created_by_email="darth.vader@posthog.com",
            state={"key": "the-new-key", "name": "a new description", "active": True},
            name="FeatureFlag",
            action="update",
            item_id=4,
            versioned_at=datetime.fromisoformat("2020-04-04T12:34:56"),
            team_id=1,
        ),
        HistoricalVersion(
            created_by_id=3,
            created_by_name="darth",
            created_by_email="darth.vader@posthog.com",
            state={"key": "the-new-key", "name": "a new description", "active": False},
            name="FeatureFlag",
            action="update",
            item_id=4,
            versioned_at=datetime.fromisoformat("2020-04-04T12:34:56"),
            team_id=1,
        ),
        HistoricalVersion(
            created_by_id=3,
            created_by_name="darth",
            created_by_email="darth.vader@posthog.com",
            state={"key": "the-new-key", "name": "a new description"},
            name="FeatureFlag",
            action="update",
            item_id=4,
            versioned_at=datetime.fromisoformat("2020-04-04T12:34:56"),
            team_id=1,
        ),
        HistoricalVersion(
            created_by_id=3,
            created_by_name="darth",
            created_by_email="darth.vader@posthog.com",
            state={"key": "the-new-key", "name": "a description"},
            name="FeatureFlag",
            action="update",
            item_id=4,
            versioned_at=datetime.fromisoformat("2020-04-03T12:34:56"),
            team_id=1,
        ),
        HistoricalVersion(
            created_by_id=3,
            created_by_name="darth",
            created_by_email="darth.vader@posthog.com",
            state={"key": "the-new-key"},
            name="FeatureFlag",
            action="update",
            item_id=4,
            versioned_at=datetime.fromisoformat("2020-04-02T12:34:56"),
            team_id=1,
        ),
        # original creation
        HistoricalVersion(
            created_by_id=2,
            created_by_name="han",
            created_by_email="han.solo@posthog.com",
            state={"key": "the-key"},
            name="FeatureFlag",
            action="create",
            item_id=4,
            versioned_at=datetime.fromisoformat("2020-04-01T12:34:56"),
            team_id=1,
        ),
    ]

    expected = [
        HistoryListItem(
            email="darth.vader@posthog.com",
            name="darth",
            user_id=3,
            action="changed_filters_on_FeatureFlag",
            detail={"id": 4, "key": "the-new-key", "from": {"some": "json"}, "to": {"some": "json", "and": "more"}},
            created_at="2020-04-04T12:34:56",
        ),
        HistoryListItem(
            email="darth.vader@posthog.com",
            name="darth",
            user_id=3,
            action="added_filters_to_FeatureFlag",
            detail={"id": 4, "key": "the-new-key", "added": {"some": "json"}},
            created_at="2020-04-04T12:34:56",
        ),
        HistoryListItem(
            email="darth.vader@posthog.com",
            name="darth",
            user_id=3,
            action="added_deleted_to_FeatureFlag",
            detail={"id": 4, "key": "the-new-key", "added": True},
            created_at="2020-04-04T12:34:56",
        ),
        HistoryListItem(
            email="darth.vader@posthog.com",
            name="darth",
            user_id=3,
            action="changed_rollout_percentage_on_FeatureFlag",
            detail={"id": 4, "key": "the-new-key", "from": 50, "to": 25},
            created_at="2020-04-04T12:34:56",
        ),
        HistoryListItem(
            email="darth.vader@posthog.com",
            name="darth",
            user_id=3,
            action="added_rollout_percentage_to_FeatureFlag",
            detail={"id": 4, "key": "the-new-key", "added": 50},
            created_at="2020-04-04T12:34:56",
        ),
        HistoryListItem(
            email="darth.vader@posthog.com",
            name="darth",
            user_id=3,
            action="changed_active_on_FeatureFlag",
            detail={"id": 4, "key": "the-new-key", "from": False, "to": True},
            created_at="2020-04-04T12:34:56",
        ),
        HistoryListItem(
            email="darth.vader@posthog.com",
            name="darth",
            user_id=3,
            action="added_active_to_FeatureFlag",
            detail={"id": 4, "key": "the-new-key", "added": False},
            created_at="2020-04-04T12:34:56",
        ),
        HistoryListItem(
            email="darth.vader@posthog.com",
            name="darth",
            user_id=3,
            action="changed_name_on_FeatureFlag",
            detail={"id": 4, "key": "the-new-key", "from": "a description", "to": "a new description"},
            created_at="2020-04-04T12:34:56",
        ),
        HistoryListItem(
            email="darth.vader@posthog.com",
            name="darth",
            user_id=3,
            action="added_name_to_FeatureFlag",
            detail={"id": 4, "key": "the-new-key", "added": "a description"},
            created_at="2020-04-03T12:34:56",
        ),
        HistoryListItem(
            email="darth.vader@posthog.com",
            name="darth",
            user_id=3,
            action="changed_key_on_FeatureFlag",
            detail={"id": 4, "key": "the-new-key", "from": "the-key", "to": "the-new-key"},
            created_at="2020-04-02T12:34:56",
        ),
        HistoryListItem(
            email="han.solo@posthog.com",
            name="han",
            user_id=2,
            action="created_FeatureFlag",
            detail={"id": 4, "key": "the-key"},
            created_at="2020-04-01T12:34:56",
        ),
    ]
    history = compute_history("FeatureFlag", pairwise(versions))
    assert history == expected
