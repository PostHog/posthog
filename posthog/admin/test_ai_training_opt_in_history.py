from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.admin.ai_training_opt_in_history import get_ai_training_opt_in_history
from posthog.models.organization import Organization, OrganizationMembership


class TestAITrainingOptInHistory(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

    def _set_opt_in_without_logging(self, value: bool | None) -> None:
        # Mirrors how the organization gets its starting value: the creation default and the
        # column's migration default both land in Postgres without an activity log row.
        Organization.objects.filter(pk=self.organization.pk).update(is_ai_training_opted_in=value)
        self.organization.refresh_from_db()

    def _patch_organization(self, updates: dict) -> None:
        response = self.client.patch(f"/api/organizations/{self.organization.id}/", updates, format="json")
        self.assertEqual(response.status_code, 200, response.json())
        self.organization.refresh_from_db()

    @parameterized.expand(
        [
            (False, "Never opted in"),
            (None, "Never opted in (value is null)"),
            (True, "Currently opted in"),
        ]
    )
    def test_headline_without_any_recorded_change(self, current: bool | None, expected_headline: str) -> None:
        self._set_opt_in_without_logging(current)

        history = get_ai_training_opt_in_history(self.organization)

        self.assertEqual(history.headline, expected_headline)
        self.assertEqual(history.changes, [])

    def test_manual_opt_in_then_opt_out_is_attributed_to_the_user_who_made_it(self) -> None:
        self._set_opt_in_without_logging(False)

        self._patch_organization({"is_ai_training_opted_in": True})
        self._patch_organization({"is_ai_training_opted_in": False})

        history = get_ai_training_opt_in_history(self.organization)

        self.assertEqual(history.headline, "Currently opted out, was opted in previously")
        self.assertEqual(
            [(c.before, c.after, c.origin, c.actor) for c in history.changes],
            [
                (False, True, "manual", self.user.email),
                (True, False, "manual", self.user.email),
            ],
        )

    def test_change_without_a_user_is_labelled_automatic(self) -> None:
        self._set_opt_in_without_logging(True)

        self.organization.is_ai_training_opted_in = False
        self.organization.save()

        history = get_ai_training_opt_in_history(self.organization)

        self.assertEqual(len(history.changes), 1)
        self.assertEqual(history.changes[0].origin, "automatic")
        self.assertEqual(history.changes[0].actor, "system")

    def test_reads_the_opt_in_change_out_of_a_multi_field_update(self) -> None:
        self._set_opt_in_without_logging(False)

        self._patch_organization({"name": "Renamed org", "is_ai_training_opted_in": True})

        history = get_ai_training_opt_in_history(self.organization)

        self.assertEqual(len(history.changes), 1)
        self.assertEqual((history.changes[0].before, history.changes[0].after), (False, True))

    def test_changes_to_other_organization_fields_are_excluded(self) -> None:
        self._patch_organization({"name": "Renamed org"})
        self._patch_organization({"is_ai_data_processing_approved": False})

        history = get_ai_training_opt_in_history(self.organization)

        self.assertEqual(history.changes, [])
