from django.test import TestCase

from posthog.models.activity_logging.activity_log import Change, dict_changes_between


class TeatActivityLog(TestCase):
    def test_dict_changes_between(self):
        changes = dict_changes_between(
            model_type="Plugin",
            previous={"change_field": "foo", "delete_field": "foo"},
            new={"change_field": "bar", "new_field": "bar"},
        )

        self.assertEqual(len(changes), 3)

        self.assertIn(
            Change(
                type="Plugin",
                action="changed",
                field="change_field",
                before="foo",
                after="bar",
            ),
            changes,
        )
        self.assertIn(
            Change(
                type="Plugin",
                action="created",
                field="new_field",
                before=None,
                after="bar",
            ),
            changes,
        )
        self.assertIn(
            Change(
                type="Plugin",
                action="deleted",
                field="delete_field",
                before="foo",
                after=None,
            ),
            changes,
        )
