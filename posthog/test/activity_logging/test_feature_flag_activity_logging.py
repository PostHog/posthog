from typing import Optional

from posthog.test.base import APIBaseTest

from dateutil import parser

from posthog.models import FeatureFlag
from posthog.models.activity_logging.activity_log import Change, changes_between


class TestChangesBetweenFeatureFlags(APIBaseTest):
    def test_comparing_two_nothings_results_in_no_changes(self) -> None:
        actual = changes_between(model_type="FeatureFlag", previous=None, current=None)
        assert actual == []

    def test_a_change_of_name_can_be_logged(self) -> None:
        actual = changes_between(
            model_type="FeatureFlag",
            previous=self._a_feature_flag_with(name="a"),
            current=self._a_feature_flag_with(name="b"),
        )
        expected = [
            Change(
                type="FeatureFlag",
                field="name",
                action="changed",
                before="a",
                after="b",
            )
        ]
        assert actual == expected

    def test_a_change_of_key_can_be_logged(self) -> None:
        actual = changes_between(
            model_type="FeatureFlag",
            previous=self._a_feature_flag_with(key="the-key"),
            current=self._a_feature_flag_with(key="the-new-key"),
        )
        expected = [
            Change(
                type="FeatureFlag",
                field="key",
                action="changed",
                before="the-key",
                after="the-new-key",
            )
        ]
        assert actual == expected

    def test_a_change_of_flag_active_status_can_be_logged(self) -> None:
        actual = changes_between(
            model_type="FeatureFlag",
            previous=self._a_feature_flag_with(active=False),
            current=self._a_feature_flag_with(active=True),
        )
        expected = [
            Change(
                type="FeatureFlag",
                field="active",
                action="changed",
                before=False,
                after=True,
            )
        ]
        assert actual == expected

    def test_adding_a_rollout_percentage_can_be_logged(self) -> None:
        actual = changes_between(
            model_type="FeatureFlag",
            previous=self._a_feature_flag_with(),
            current=self._a_feature_flag_with(rollout_percentage=23),
        )
        expected = [
            Change(
                type="FeatureFlag",
                field="rollout_percentage",
                action="created",
                after=23,
            )
        ]
        assert actual == expected

    def test_a_change_of_rollout_percentage_can_be_logged(self) -> None:
        actual = changes_between(
            model_type="FeatureFlag",
            previous=self._a_feature_flag_with(rollout_percentage=12),
            current=self._a_feature_flag_with(rollout_percentage=23),
        )
        expected = [
            Change(
                type="FeatureFlag",
                field="rollout_percentage",
                action="changed",
                before=12,
                after=23,
            )
        ]
        assert actual == expected

    def test_a_change_of_soft_delete_can_be_logged(self) -> None:
        actual = changes_between(
            model_type="FeatureFlag",
            previous=self._a_feature_flag_with(deleted=False),
            current=self._a_feature_flag_with(deleted=True),
        )
        expected = [
            Change(
                type="FeatureFlag",
                field="deleted",
                action="changed",
                before=False,
                after=True,
            )
        ]
        assert actual == expected

    def test_a_change_of_filters_can_be_logged(self) -> None:
        actual = changes_between(
            model_type="FeatureFlag",
            previous=self._a_feature_flag_with(filters={"some": "value"}),
            current=self._a_feature_flag_with(filters={"new": "content"}),
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

    def test_can_exclude_changed_fields_in_feature_flags(self) -> None:
        actual = changes_between(
            model_type="FeatureFlag",
            previous=self._a_feature_flag_with(created_at="before", created_by="before", is_simple_flag=True),
            current=self._a_feature_flag_with(created_at="after", created_by="after", is_simple_flag=False),
        )
        self.assertEqual(actual, [])

    @staticmethod
    def _a_feature_flag_with(id: Optional[int] = None, **kwargs) -> FeatureFlag:
        if not id:
            id = 2

        return FeatureFlag(
            deleted=kwargs.get("deleted", False),
            rollout_percentage=kwargs.get("rollout_percentage", None),
            active=kwargs.get("active", True),
            id=id,
            key=kwargs.get("key", "the-key"),
            name=kwargs.get("name", "a"),
            filters=kwargs.get("filters", None),
            created_at=parser.parse("12th April 2003"),
        )
