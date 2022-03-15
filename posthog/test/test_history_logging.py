from datetime import datetime

from freezegun.api import freeze_time

from posthog.models import HistoricalVersion, User
from posthog.models.history_logging import Change, HistoryListItem, compute_history, pairwise


@freeze_time("2021-08-25T22:09:14.252Z")
def test_no_history_shows_updated_by_history_hog():
    actual = compute_history(history_type="FeatureFlag", version_pairs=[])
    expected = [
        HistoryListItem(
            email="history.hog@posthog.com",
            name="History Hog",
            changes=[Change(type="FeatureFlag", key=None, action="imported", detail={})],
            created_at="2021-08-25T22:09:14.252000",
        )
    ]
    assert actual == expected


def test_a_single_update_shows_updated_by_history_hog():
    an_update = HistoricalVersion(
        state={"key": "the-key"},
        name="FeatureFlag",
        action="not create",
        item_id=4,
        versioned_at=datetime.fromisoformat("2020-04-01T12:34:56"),
        team_id=1,
    )
    actual = compute_history(history_type="FeatureFlag", version_pairs=[(an_update, None)])
    expected = [
        HistoryListItem(
            email="history.hog@posthog.com",
            name="History Hog",
            changes=[Change(type="FeatureFlag", key=None, action="imported", detail={"id": 4, "key": "the-key"})],
            created_at="2020-04-01T12:34:56",
        )
    ]
    assert actual == expected


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
        HistoricalVersion(  # edits the filter
            created_by=User(first_name="darth", email="darth.vader@posthog.com"),
            state={
                "key": "the-new-key",
                "name": "a new description",
                "active": True,
                "rollout_percentage": 25,
                "deleted": False,
                "filters": {"some": "json", "and": "more"},
            },
            name="FeatureFlag",
            action="update",
            item_id=4,
            versioned_at=datetime.fromisoformat("2020-04-04T12:53:56"),
            team_id=1,
        ),
        HistoricalVersion(  # sets a filter and undo soft delete
            created_by=User(first_name="darth", email="darth.vader@posthog.com"),
            state={
                "key": "the-new-key",
                "name": "a new description",
                "active": True,
                "rollout_percentage": 25,
                "deleted": False,
                "filters": {"some": "json"},
            },
            name="FeatureFlag",
            action="update",
            item_id=4,
            versioned_at=datetime.fromisoformat("2020-04-04T12:52:56"),
            team_id=1,
        ),
        HistoricalVersion(  # soft deletes the flag
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
            versioned_at=datetime.fromisoformat("2020-04-04T12:51:56"),
            team_id=1,
        ),
        HistoricalVersion(  # changes the roll out percentage
            created_by=User(first_name="darth", email="darth.vader@posthog.com"),
            state={"key": "the-new-key", "name": "a new description", "active": True, "rollout_percentage": 25},
            name="FeatureFlag",
            action="update",
            item_id=4,
            versioned_at=datetime.fromisoformat("2020-04-04T12:50:56"),
            team_id=1,
        ),
        HistoricalVersion(  # adds a rollout percentage
            created_by=User(first_name="darth", email="darth.vader@posthog.com"),
            state={"key": "the-new-key", "name": "a new description", "active": True, "rollout_percentage": 50},
            name="FeatureFlag",
            action="update",
            item_id=4,
            versioned_at=datetime.fromisoformat("2020-04-04T12:49:56"),
            team_id=1,
        ),
        HistoricalVersion(  # sets active to True
            created_by=User(first_name="darth", email="darth.vader@posthog.com"),
            state={"key": "the-new-key", "name": "a new description", "active": True},
            name="FeatureFlag",
            action="update",
            item_id=4,
            versioned_at=datetime.fromisoformat("2020-04-04T12:48:56"),
            team_id=1,
        ),
        HistoricalVersion(  # sets active to False
            created_by=User(first_name="darth", email="darth.vader@posthog.com"),
            state={"key": "the-new-key", "name": "a new description", "active": False},
            name="FeatureFlag",
            action="update",
            item_id=4,
            versioned_at=datetime.fromisoformat("2020-04-04T12:47:56"),
            team_id=1,
        ),
        HistoricalVersion(  # changes the name
            created_by=User(first_name="darth", email="darth.vader@posthog.com"),
            state={"key": "the-new-key", "name": "a new description"},
            name="FeatureFlag",
            action="update",
            item_id=4,
            versioned_at=datetime.fromisoformat("2020-04-04T12:46:56"),
            team_id=1,
        ),
        HistoricalVersion(  # changes the key and adds a name
            created_by=User(first_name="darth", email="darth.vader@posthog.com"),
            state={"key": "the-new-key", "name": "a description"},
            name="FeatureFlag",
            action="update",
            item_id=4,
            versioned_at=datetime.fromisoformat("2020-04-04T12:45:56"),
            team_id=1,
        ),
        HistoricalVersion(  # original creation
            created_by=User(first_name="han", email="han.solo@posthog.com"),
            state={"key": "the-key"},
            name="FeatureFlag",
            action="create",
            item_id=4,
            versioned_at=datetime.fromisoformat("2020-04-04T12:44:56"),
            team_id=1,
        ),
    ]

    expected = [
        HistoryListItem(  # edits the filter
            email="darth.vader@posthog.com",
            name="darth",
            changes=[
                Change(
                    type="FeatureFlag",
                    key="filters",
                    action="changed",
                    detail={
                        "id": 4,
                        "key": "the-new-key",
                        "from": {"some": "json"},
                        "to": {"some": "json", "and": "more"},
                    },
                )
            ],
            created_at="2020-04-04T12:53:56",
        ),
        HistoryListItem(  # sets a filter and undo soft delete
            email="darth.vader@posthog.com",
            name="darth",
            changes=[
                Change(
                    type="FeatureFlag",
                    key="deleted",
                    action="changed",
                    detail={"id": 4, "key": "the-new-key", "from": True, "to": False},
                ),
                Change(
                    type="FeatureFlag",
                    key="filters",
                    action="changed",
                    detail={"id": 4, "key": "the-new-key", "to": {"some": "json"}},
                ),
            ],
            created_at="2020-04-04T12:52:56",
        ),
        HistoryListItem(  # soft deletes the flag
            email="darth.vader@posthog.com",
            name="darth",
            changes=[
                Change(
                    type="FeatureFlag",
                    key="deleted",
                    action="changed",
                    detail={"id": 4, "key": "the-new-key", "to": True},
                )
            ],
            created_at="2020-04-04T12:51:56",
        ),
        HistoryListItem(  # changes the rollout percentage
            email="darth.vader@posthog.com",
            name="darth",
            changes=[
                Change(
                    type="FeatureFlag",
                    key="rollout_percentage",
                    action="changed",
                    detail={"id": 4, "key": "the-new-key", "from": 50, "to": 25},
                )
            ],
            created_at="2020-04-04T12:50:56",
        ),
        HistoryListItem(  # adds a rollout percentage
            email="darth.vader@posthog.com",
            name="darth",
            changes=[
                Change(
                    type="FeatureFlag",
                    key="rollout_percentage",
                    action="changed",
                    detail={"id": 4, "key": "the-new-key", "to": 50},
                )
            ],
            created_at="2020-04-04T12:49:56",
        ),
        HistoryListItem(  # sets active to True
            email="darth.vader@posthog.com",
            name="darth",
            changes=[
                Change(
                    type="FeatureFlag",
                    key="active",
                    action="changed",
                    detail={"id": 4, "key": "the-new-key", "from": False, "to": True},
                )
            ],
            created_at="2020-04-04T12:48:56",
        ),
        HistoryListItem(  # sets active to False
            email="darth.vader@posthog.com",
            name="darth",
            changes=[
                Change(
                    type="FeatureFlag",
                    key="active",
                    action="changed",
                    detail={"id": 4, "key": "the-new-key", "to": False},
                )
            ],
            created_at="2020-04-04T12:47:56",
        ),
        HistoryListItem(  # changes the name
            email="darth.vader@posthog.com",
            name="darth",
            changes=[
                Change(
                    type="FeatureFlag",
                    key="name",
                    action="changed",
                    detail={"id": 4, "key": "the-new-key", "from": "a description", "to": "a new description"},
                )
            ],
            created_at="2020-04-04T12:46:56",
        ),
        HistoryListItem(  # changes the key and adds a name
            email="darth.vader@posthog.com",
            name="darth",
            changes=[
                Change(
                    type="FeatureFlag",
                    key="key",
                    action="changed",
                    detail={"id": 4, "key": "the-new-key", "from": "the-key", "to": "the-new-key"},
                ),
                Change(
                    type="FeatureFlag",
                    key="name",
                    action="changed",
                    detail={"id": 4, "key": "the-new-key", "to": "a description"},
                ),
            ],
            created_at="2020-04-04T12:45:56",
        ),
        HistoryListItem(  # original creation
            email="han.solo@posthog.com",
            name="han",
            changes=[Change(type="FeatureFlag", key=None, action="created", detail={"id": 4, "key": "the-key"},)],
            created_at="2020-04-04T12:44:56",
        ),
    ]
    history = compute_history(history_type="FeatureFlag", version_pairs=pairwise(versions))
    assert history == expected
