import unittest

import pytest
from dateutil import parser
from django.db.utils import IntegrityError

from posthog.models import FeatureFlag, Person, Team, User
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

    def test_does_not_save_an_updated_activity_that_has_no_changes(self):
        log_activity(
            organization_id=self.organization.id,
            team_id=self.team.id,
            user=self.user,
            item_id=None,
            scope="dinglehopper",
            activity="updated",
            detail=Detail(),
        )
        with pytest.raises(ActivityLog.DoesNotExist):
            ActivityLog.objects.latest("id")

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

    def test_does_not_throw_if_cannot_log_activity(self):
        with self.assertLogs(level="WARN") as log:
            try:
                log_activity(
                    organization_id=UUIDT(),
                    team_id=1,
                    # will cause logging to raise exception because user is unsaved
                    # avoids needing to mock anything to force the exception
                    user=User(first_name="testy", email="test@example.com"),
                    item_id="12345",
                    scope="testing throwing exceptions on create",
                    activity="does not explode",
                    detail=Detail(),
                )
            except Exception as e:
                raise pytest.fail(f"Should not have raised exception: {e}")

            logged_warning = log.records[0].__dict__
            self.assertEqual(logged_warning["levelname"], "WARNING")
            self.assertEqual(logged_warning["msg"]["event"], "failed to write activity log")
            self.assertEqual(logged_warning["msg"]["scope"], "testing throwing exceptions on create")
            self.assertEqual(logged_warning["msg"]["team"], 1)
            self.assertEqual(logged_warning["msg"]["activity"], "does not explode")
            self.assertIsInstance(logged_warning["msg"]["exception"], ValueError)


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

    def test_can_exclude_changed_fields_in_feature_flags(self):
        """field_exclusions: Dict[Literal["FeatureFlag", "Person"], List[str]] = {
            "FeatureFlag": ["id", "created_at", "created_by", "is_simple_flag",],
            "Person": ["id", "uuid", "distinct_ids", "name", "created_at", "is_identified",],
        }
        """
        actual = changes_between(
            model_type="FeatureFlag",
            previous=self._a_feature_flag_with(
                id="before", created_at="before", created_by="before", is_simple_flag=True
            ),
            current=self._a_feature_flag_with(id="after", created_at="after", created_by="after", is_simple_flag=False),
        )
        self.assertEqual(actual, [])

    def test_can_exclude_changed_fields_in_persons(self):
        """field_exclusions: Dict[Literal["FeatureFlag", "Person"], List[str]] = {
            "FeatureFlag": ["id", "created_at", "created_by", "is_simple_flag",],
            "Person": ["id", "uuid", "distinct_ids", "name", "created_at", "is_identified",],
        }
        """
        actual = changes_between(
            model_type="Person",
            previous=self._a_person_with(
                id="before", uuid="before", distinct_ids="before", created_at="before", is_identified=True
            ),
            current=self._a_person_with(
                id="after", uuid="after", distinct_ids="after", created_at="after", is_identified=False
            ),
        )
        self.assertEqual([change.field for change in actual], ["team", "is_user"])

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

    @staticmethod
    def _a_person_with(**kwargs) -> Person:
        return Person(
            id=kwargs.get("id", 2),
            created_at=kwargs.get("created_at", parser.parse("12th April 2003")),
            properties_last_updated_at=kwargs.get("properties_last_updated_at", parser.parse("12th April 2003")),
            properties_last_operation=kwargs.get("properties_last_operation", {}),
            team=kwargs.get("team", Team()),
            properties=kwargs.get("properties", {}),
            is_user=kwargs.get("is_user", User()),
            is_identified=kwargs.get("is_identified", True),
            uuid=kwargs.get("uuid", UUIDT()),
            version=kwargs.get("version", 1),
        )
