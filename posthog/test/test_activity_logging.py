import unittest

from dateutil import parser
from django.db.utils import IntegrityError

from posthog.models import FeatureFlag
from posthog.models.activity_logging.activity_log import (
    ActivityLog,
    ActivityPage,
    Change,
    Detail,
    changes_between,
    log_activity,
)
from posthog.models.utils import UUIDT
from posthog.test.base import BaseTest


class TestActivityPaging(unittest.TestCase):
    def test_first_page_of_small_dataset(self):
        actual = ActivityPage(total_count=9, offset=0, limit=10, results=[])
        self.assertEqual(actual.has_next(), False)

    def test_first_page_of_larger_dataset(self):
        actual = ActivityPage(total_count=20, offset=0, limit=10, results=[])
        self.assertEqual(actual.has_next(), True)

    def test_middle_page_of_dataset(self):
        actual = ActivityPage(total_count=30, offset=10, limit=10, results=[])
        self.assertEqual(actual.has_next(), True)

    def test_last_page_of_dataset(self):
        actual = ActivityPage(total_count=110, offset=100, limit=10, results=[])
        self.assertEqual(actual.has_next(), False)


class TestActivityLogModel(BaseTest):
    def test_can_save_a_model_changed_activity_log(self):
        change = Change(type="FeatureFlag", field="active", action="created", before=False, after=True)
        log_activity(
            organization_id=self.organization.id,
            team_id=self.team.id,
            user=self.user,
            item_id=6,
            scope="FeatureFlag",
            activity="updated",
            detail=(Detail(changes=[change])),
        )
        log: ActivityLog = ActivityLog.objects.latest("id")

        self.assertEqual(log.team_id, self.team.id)
        self.assertEqual(log.organization_id, self.organization.id)
        self.assertEqual(log.user, self.user)
        self.assertEqual(log.item_id, "6")
        self.assertEqual(log.scope, "FeatureFlag")
        self.assertEqual(log.activity, "updated")
        self.assertEqual(log.detail["changes"], [change.__dict__])

    def test_can_save_a_log_that_has_no_model_changes(self):
        log_activity(
            organization_id=self.organization.id,
            team_id=self.team.id,
            user=self.user,
            item_id=None,
            scope="dinglehopper",
            activity="added_to_clink_expander",
            detail=Detail(),
        )
        log: ActivityLog = ActivityLog.objects.latest("id")
        self.assertEqual(log.activity, "added_to_clink_expander")

    def test_can_not_save_if_there_is_neither_a_team_id_nor_an_organisation_id(self):
        # even when there are logs with team id or org id saved
        ActivityLog.objects.create(team_id=3)
        ActivityLog.objects.create(organization_id=UUIDT())
        # we cannot save a new log if it has neither team nor org id
        with self.assertRaises(IntegrityError) as error:
            ActivityLog.objects.create()

        self.assertIn(
            'new row for relation "posthog_activitylog" violates check constraint "must_have_team_or_organization_id',
            error.exception.args[0],
        )


class TestChangesBetweenFeatureFlags(unittest.TestCase):
    def test_comparing_two_nothings_results_in_no_changes(self):
        actual = changes_between(model_type="FeatureFlag", previous=None, current=None)
        assert actual == []

    def test_a_change_of_name_can_be_logged(self):
        actual = changes_between(
            model_type="FeatureFlag",
            previous=self._a_feature_flag_with(name="a"),
            current=self._a_feature_flag_with(name="b"),
        )
        expected = [Change(type="FeatureFlag", field="name", action="changed", before="a", after="b")]
        assert actual == expected

    def test_a_change_of_key_can_be_logged(self):
        actual = changes_between(
            model_type="FeatureFlag",
            previous=self._a_feature_flag_with(key="the-key"),
            current=self._a_feature_flag_with(key="the-new-key"),
        )
        expected = [Change(type="FeatureFlag", field="key", action="changed", before="the-key", after="the-new-key",)]
        assert actual == expected

    def test_a_change_of_flag_active_status_can_be_logged(self):
        actual = changes_between(
            model_type="FeatureFlag",
            previous=self._a_feature_flag_with(active=False),
            current=self._a_feature_flag_with(active=True),
        )
        expected = [Change(type="FeatureFlag", field="active", action="changed", before=False, after=True,)]
        assert actual == expected

    def test_adding_a_rollout_percentage_can_be_logged(self):
        actual = changes_between(
            model_type="FeatureFlag",
            previous=self._a_feature_flag_with(),
            current=self._a_feature_flag_with(rollout_percentage=23,),
        )
        expected = [Change(type="FeatureFlag", field="rollout_percentage", action="created", after=23)]
        assert actual == expected

    def test_a_change_of_rollout_percentage_can_be_logged(self):
        actual = changes_between(
            model_type="FeatureFlag",
            previous=self._a_feature_flag_with(rollout_percentage=12,),
            current=self._a_feature_flag_with(rollout_percentage=23,),
        )
        expected = [Change(type="FeatureFlag", field="rollout_percentage", action="changed", before=12, after=23)]
        assert actual == expected

    def test_a_change_of_soft_delete_can_be_logged(self):
        actual = changes_between(
            model_type="FeatureFlag",
            previous=self._a_feature_flag_with(deleted=False,),
            current=self._a_feature_flag_with(deleted=True,),
        )
        expected = [Change(type="FeatureFlag", field="deleted", action="changed", before=False, after=True,)]
        assert actual == expected

    def test_a_change_of_filters_can_be_logged(self):
        actual = changes_between(
            model_type="FeatureFlag",
            previous=self._a_feature_flag_with(filters={"some": "value"},),
            current=self._a_feature_flag_with(filters={"new": "content"},),
        )
        expected = [
            Change(
                type="FeatureFlag",
                field="filters",
                action="changed",
                before={"some": "value"},
                after={"new": "content"},
            )
        ]
        assert actual == expected

    @staticmethod
    def _a_feature_flag_with(**kwargs) -> FeatureFlag:
        return FeatureFlag(
            deleted=kwargs.get("deleted", False),
            rollout_percentage=kwargs.get("rollout_percentage", None),
            active=kwargs.get("active", True),
            id=kwargs.get("id", 2),
            key=kwargs.get("key", "the-key"),
            name=kwargs.get("name", "a"),
            filters=kwargs.get("filters", None),
            created_at=parser.parse("12th April 2003"),
        )
