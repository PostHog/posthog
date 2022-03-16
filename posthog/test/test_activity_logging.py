from dateutil import parser
from django.db.utils import IntegrityError

from posthog.models import FeatureFlag
from posthog.models.activity_logging.activity_log import ActivityLog, Change, Detail, changes_between, log_activity
from posthog.models.utils import UUIDT
from posthog.test.base import BaseTest


class TestActivityLogModel(BaseTest):
    def test_can_save_a_model_changed_activity_log(self):
        change = Change(type="FeatureFlag", field="active", action="created", before=False, after=True)
        log_activity(
            organization_id=self.organization.id,
            team_id=self.team.id,
            user=self.user,
            item_id=6,
            item_type="FeatureFlag",
            activity="updated",
            detail=(Detail(changes=[change])),
        )
        log: ActivityLog = ActivityLog.objects.latest("id")

        self.assertEqual(log.team_id, self.team.id)
        self.assertEqual(log.organization_id, self.organization.id)
        self.assertEqual(log.user, self.user)
        self.assertEqual(log.item_id, "6")
        self.assertEqual(log.item_type, "FeatureFlag")
        self.assertEqual(log.activity, "updated")
        self.assertEqual(log.detail["changes"], [change.__dict__])

    def test_can_save_a_log_that_has_no_model_changes(self):
        log_activity(
            organization_id=self.organization.id,
            team_id=self.team.id,
            user=self.user,
            item_id=6,
            item_type="dinglehopper",
            activity="added_to_clink_expander",
            detail=Detail(),
        )
        log: ActivityLog = ActivityLog.objects.latest("id")
        self.assertEqual(log.activity, "added_to_clink_expander")

    def test_can_not_save_if_there_is_neither_a_team_id_nor_an_organisation_id(self):
        # even when there are logs with team id or org id saved
        ActivityLog.objects.create(team_id=3)
        ActivityLog.objects.create(organization_id=UUIDT())
        # we cannot save a new version if it has neither team nor org id
        with self.assertRaises(IntegrityError) as error:
            ActivityLog.objects.create()

        self.assertIn(
            'new row for relation "posthog_activitylog" violates check constraint "must_have_team_or_organization_id',
            error.exception.args[0],
        )


def test_comparing_two_nothings_results_in_no_changes():
    actual = changes_between(model_type="FeatureFlag", previous=None, current=None)
    assert actual == []


def test_a_change_of_name_can_be_logged():
    actual = changes_between(
        model_type="FeatureFlag",
        previous=FeatureFlag(id=2, key="the-key", name="a", created_at=parser.parse("12th April 2003")),
        current=FeatureFlag(id=2, key="the-key", name="b", created_at=parser.parse("12th April 2003")),
    )
    expected = [Change(type="FeatureFlag", field="name", action="changed", before="a", after="b")]
    assert actual == expected


def test_a_change_of_key_can_be_logged():
    actual = changes_between(
        model_type="FeatureFlag",
        previous=FeatureFlag(id=2, key="the-key", name="a", created_at=parser.parse("12th April 2003")),
        current=FeatureFlag(id=2, key="the-new-key", name="a", created_at=parser.parse("12th April 2003")),
    )
    expected = [Change(type="FeatureFlag", field="key", action="changed", before="the-key", after="the-new-key",)]
    assert actual == expected


def test_a_change_of_flag_active_status_can_be_logged():
    actual = changes_between(
        model_type="FeatureFlag",
        previous=FeatureFlag(active=False, id=2, key="the-key", name="a", created_at=parser.parse("12th April 2003")),
        current=FeatureFlag(active=True, id=2, key="the-key", name="a", created_at=parser.parse("12th April 2003")),
    )
    expected = [Change(type="FeatureFlag", field="active", action="changed", before=False, after=True,)]
    assert actual == expected


def test_adding_a_rollout_percentage_can_be_logged():
    actual = changes_between(
        model_type="FeatureFlag",
        previous=FeatureFlag(active=True, id=2, key="the-key", name="a", created_at=parser.parse("12th April 2003"),),
        current=FeatureFlag(
            rollout_percentage=23,
            active=True,
            id=2,
            key="the-key",
            name="a",
            created_at=parser.parse("12th April 2003"),
        ),
    )
    expected = [Change(type="FeatureFlag", field="rollout_percentage", action="created", after=23)]
    assert actual == expected


def test_a_change_of_rollout_percentage_can_be_logged():
    actual = changes_between(
        model_type="FeatureFlag",
        previous=FeatureFlag(
            rollout_percentage=12,
            active=True,
            id=2,
            key="the-key",
            name="a",
            created_at=parser.parse("12th April 2003"),
        ),
        current=FeatureFlag(
            rollout_percentage=23,
            active=True,
            id=2,
            key="the-key",
            name="a",
            created_at=parser.parse("12th April 2003"),
        ),
    )
    expected = [Change(type="FeatureFlag", field="rollout_percentage", action="changed", before=12, after=23)]
    assert actual == expected


def test_a_change_of_soft_delete_can_be_logged():
    actual = changes_between(
        model_type="FeatureFlag",
        previous=FeatureFlag(
            deleted=False,
            rollout_percentage=23,
            active=True,
            id=2,
            key="the-key",
            name="a",
            created_at=parser.parse("12th April 2003"),
        ),
        current=FeatureFlag(
            deleted=True,
            rollout_percentage=23,
            active=True,
            id=2,
            key="the-key",
            name="a",
            created_at=parser.parse("12th April 2003"),
        ),
    )
    expected = [Change(type="FeatureFlag", field="deleted", action="changed", before=False, after=True,)]
    assert actual == expected


def test_a_change_of_filters_can_be_logged():
    actual = changes_between(
        model_type="FeatureFlag",
        previous=FeatureFlag(
            filters={"some": "value"},
            deleted=False,
            rollout_percentage=23,
            active=True,
            id=2,
            key="the-key",
            name="a",
            created_at=parser.parse("12th April 2003"),
        ),
        current=FeatureFlag(
            filters={"new": "content"},
            deleted=False,
            rollout_percentage=23,
            active=True,
            id=2,
            key="the-key",
            name="a",
            created_at=parser.parse("12th April 2003"),
        ),
    )
    expected = [
        Change(
            type="FeatureFlag", field="filters", action="changed", before={"some": "value"}, after={"new": "content"},
        )
    ]
    assert actual == expected
