from datetime import datetime

from posthog.models import HistoricalVersion, User
from posthog.models.history_logging import HistoryListItem, compute_history, pairwise


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
    assert compute_history(history_type="FeatureFlag", version_pairs=[(an_update, None)]) == [
        HistoryListItem(
            email="history.hog@posthog.com",
            name="history hog",
            action="FeatureFlag_imported",
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
            created_by=User(first_name="darth", email="darth.vader@posthog.com"),
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
            created_by=User(first_name="darth", email="darth.vader@posthog.com"),
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
            created_by=User(first_name="darth", email="darth.vader@posthog.com"),
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
            created_by=User(first_name="darth", email="darth.vader@posthog.com"),
            state={"key": "the-new-key", "name": "a new description", "active": True, "rollout_percentage": 25},
            name="FeatureFlag",
            action="update",
            item_id=4,
            versioned_at=datetime.fromisoformat("2020-04-04T12:34:56"),
            team_id=1,
        ),
        HistoricalVersion(
            created_by=User(first_name="darth", email="darth.vader@posthog.com"),
            state={"key": "the-new-key", "name": "a new description", "active": True, "rollout_percentage": 50},
            name="FeatureFlag",
            action="update",
            item_id=4,
            versioned_at=datetime.fromisoformat("2020-04-04T12:34:56"),
            team_id=1,
        ),
        HistoricalVersion(
            created_by=User(first_name="darth", email="darth.vader@posthog.com"),
            state={"key": "the-new-key", "name": "a new description", "active": True},
            name="FeatureFlag",
            action="update",
            item_id=4,
            versioned_at=datetime.fromisoformat("2020-04-04T12:34:56"),
            team_id=1,
        ),
        HistoricalVersion(
            created_by=User(first_name="darth", email="darth.vader@posthog.com"),
            state={"key": "the-new-key", "name": "a new description", "active": False},
            name="FeatureFlag",
            action="update",
            item_id=4,
            versioned_at=datetime.fromisoformat("2020-04-04T12:34:56"),
            team_id=1,
        ),
        HistoricalVersion(
            created_by=User(first_name="darth", email="darth.vader@posthog.com"),
            state={"key": "the-new-key", "name": "a new description"},
            name="FeatureFlag",
            action="update",
            item_id=4,
            versioned_at=datetime.fromisoformat("2020-04-04T12:34:56"),
            team_id=1,
        ),
        HistoricalVersion(
            created_by=User(first_name="darth", email="darth.vader@posthog.com"),
            state={"key": "the-new-key", "name": "a description"},
            name="FeatureFlag",
            action="update",
            item_id=4,
            versioned_at=datetime.fromisoformat("2020-04-03T12:34:56"),
            team_id=1,
        ),
        HistoricalVersion(
            created_by=User(first_name="darth", email="darth.vader@posthog.com"),
            state={"key": "the-new-key"},
            name="FeatureFlag",
            action="update",
            item_id=4,
            versioned_at=datetime.fromisoformat("2020-04-02T12:34:56"),
            team_id=1,
        ),
        # original creation
        HistoricalVersion(
            created_by=User(first_name="han", email="han.solo@posthog.com"),
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
            action="FeatureFlag_filters_changed",
            detail={"id": 4, "key": "the-new-key", "from": {"some": "json"}, "to": {"some": "json", "and": "more"}},
            created_at="2020-04-04T12:34:56",
        ),
        HistoryListItem(
            email="darth.vader@posthog.com",
            name="darth",
            action="FeatureFlag_filters_changed",
            detail={"id": 4, "key": "the-new-key", "to": {"some": "json"}},
            created_at="2020-04-04T12:34:56",
        ),
        HistoryListItem(
            email="darth.vader@posthog.com",
            name="darth",
            action="FeatureFlag_deleted_changed",
            detail={"id": 4, "key": "the-new-key", "to": True},
            created_at="2020-04-04T12:34:56",
        ),
        HistoryListItem(
            email="darth.vader@posthog.com",
            name="darth",
            action="FeatureFlag_rollout_percentage_changed",
            detail={"id": 4, "key": "the-new-key", "from": 50, "to": 25},
            created_at="2020-04-04T12:34:56",
        ),
        HistoryListItem(
            email="darth.vader@posthog.com",
            name="darth",
            action="FeatureFlag_rollout_percentage_changed",
            detail={"id": 4, "key": "the-new-key", "to": 50},
            created_at="2020-04-04T12:34:56",
        ),
        HistoryListItem(
            email="darth.vader@posthog.com",
            name="darth",
            action="FeatureFlag_active_changed",
            detail={"id": 4, "key": "the-new-key", "from": False, "to": True},
            created_at="2020-04-04T12:34:56",
        ),
        HistoryListItem(
            email="darth.vader@posthog.com",
            name="darth",
            action="FeatureFlag_active_changed",
            detail={"id": 4, "key": "the-new-key", "to": False},
            created_at="2020-04-04T12:34:56",
        ),
        HistoryListItem(
            email="darth.vader@posthog.com",
            name="darth",
            action="FeatureFlag_name_changed",
            detail={"id": 4, "key": "the-new-key", "from": "a description", "to": "a new description"},
            created_at="2020-04-04T12:34:56",
        ),
        HistoryListItem(
            email="darth.vader@posthog.com",
            name="darth",
            action="FeatureFlag_name_changed",
            detail={"id": 4, "key": "the-new-key", "to": "a description"},
            created_at="2020-04-03T12:34:56",
        ),
        HistoryListItem(
            email="darth.vader@posthog.com",
            name="darth",
            action="FeatureFlag_key_changed",
            detail={"id": 4, "key": "the-new-key", "from": "the-key", "to": "the-new-key"},
            created_at="2020-04-02T12:34:56",
        ),
        HistoryListItem(
            email="han.solo@posthog.com",
            name="han",
            action="FeatureFlag_created",
            detail={"id": 4, "key": "the-key"},
            created_at="2020-04-01T12:34:56",
        ),
    ]
    history = compute_history(history_type="FeatureFlag", version_pairs=pairwise(versions))
    assert history == expected
