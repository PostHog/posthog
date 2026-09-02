from posthog.test.base import APIBaseTest

from django.contrib.admin.sites import AdminSite

from parameterized import parameterized

from posthog.admin.admins.organization_admin import OrganizationAdmin
from posthog.admin.ai_training_opt_in_history import MAX_ENTRIES_SHOWN, get_ai_training_opt_in_history
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.user import User


class TestAITrainingOptInHistory(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

    def _set_opt_in_without_logging(self, value: bool | None) -> None:
        # This mirrors how an organization gets its starting value. The creation default and the
        # column's migration default both write to Postgres without an activity log row.
        Organization.objects.filter(pk=self.organization.pk).update(is_ai_training_opted_in=value)
        self.organization.refresh_from_db()

    def _log_opt_in_change(
        self, *, user: User | None, before: bool | None, after: bool | None, is_system: bool
    ) -> ActivityLog:
        return ActivityLog.objects.create(
            organization_id=self.organization.id,
            item_id=str(self.organization.id),
            scope="Organization",
            activity="updated",
            user=user,
            is_system=is_system,
            was_impersonated=False,
            detail={
                "name": self.organization.name,
                "changes": [
                    {
                        "type": "Organization",
                        "action": "changed",
                        "field": "is_ai_training_opted_in",
                        "before": before,
                        "after": after,
                    }
                ],
            },
        )

    def _patch_organization(self, updates: dict) -> None:
        response = self.client.patch(f"/api/organizations/{self.organization.id}/", updates, format="json")
        self.assertEqual(response.status_code, 200, response.json())
        self.organization.refresh_from_db()

    @parameterized.expand(
        [
            (False, "No recorded opt-in"),
            (None, "No recorded opt-in (value is null)"),
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

    @parameterized.expand(
        [
            (True, True, True),
            (True, False, False),
            (False, True, False),
            (True, None, False),
        ]
    )
    def test_warns_only_when_a_hipaa_organization_is_opted_in(
        self, is_hipaa: bool, opted_in: bool | None, expect_warning: bool
    ) -> None:
        self.organization.is_hipaa = is_hipaa
        self.organization.save()
        self._set_opt_in_without_logging(opted_in)

        history = get_ai_training_opt_in_history(self.organization)

        self.assertEqual(history.warning is not None, expect_warning)

    def test_change_by_a_since_deleted_user_is_not_reported_as_automatic(self) -> None:
        self._set_opt_in_without_logging(False)
        departed = User.objects.create_and_join(self.organization, "departed@posthog.com", None)
        self._log_opt_in_change(user=departed, before=True, after=False, is_system=False)
        departed.delete()

        history = get_ai_training_opt_in_history(self.organization)

        self.assertEqual(len(history.changes), 1)
        self.assertEqual(history.changes[0].origin, "manual")
        self.assertEqual(history.changes[0].actor, "user since deleted")

    def test_opt_in_older_than_the_cap_still_counts_towards_the_headline(self) -> None:
        self._set_opt_in_without_logging(False)
        self._log_opt_in_change(user=None, before=False, after=True, is_system=True)
        # The column accepts null, so the newest changes can alternate without ever holding True.
        # These changes push the only opt-in out of the displayed window.
        for index in range(MAX_ENTRIES_SHOWN + 1):
            before, after = (None, False) if index % 2 == 0 else (False, None)
            self._log_opt_in_change(user=None, before=before, after=after, is_system=True)

        history = get_ai_training_opt_in_history(self.organization)

        self.assertTrue(history.truncated)
        self.assertNotIn(True, [c.after for c in history.changes] + [c.before for c in history.changes])
        self.assertEqual(history.headline, "Currently opted out, was opted in previously")

    def test_history_over_the_cap_is_flagged_as_truncated(self) -> None:
        self._set_opt_in_without_logging(False)
        for index in range(MAX_ENTRIES_SHOWN + 1):
            self._log_opt_in_change(user=None, before=index % 2 == 1, after=index % 2 == 0, is_system=True)

        history = get_ai_training_opt_in_history(self.organization)

        self.assertTrue(history.truncated)
        self.assertEqual(len(history.changes), MAX_ENTRIES_SHOWN)

    def test_impersonated_change_names_the_customer_and_says_the_staff_member_is_unrecorded(self) -> None:
        self._set_opt_in_without_logging(False)
        entry = self._log_opt_in_change(user=self.user, before=True, after=False, is_system=False)
        ActivityLog.objects.filter(pk=entry.pk).update(was_impersonated=True)

        history = get_ai_training_opt_in_history(self.organization)

        self.assertEqual(history.changes[0].origin, "manual (staff impersonation)")
        self.assertIn(self.user.email, history.changes[0].actor)
        self.assertIn("not recorded", history.changes[0].actor)

    def test_row_predating_the_is_system_column_falls_back_to_the_user_column(self) -> None:
        self._set_opt_in_without_logging(False)
        entry = self._log_opt_in_change(user=None, before=True, after=False, is_system=False)
        ActivityLog.objects.filter(pk=entry.pk).update(is_system=None)

        history = get_ai_training_opt_in_history(self.organization)

        self.assertEqual(history.changes[0].origin, "automatic")
        self.assertEqual(history.changes[0].actor, "system")

    def test_admin_panel_renders_the_headline_and_the_change_rows(self) -> None:
        self._set_opt_in_without_logging(False)
        self._patch_organization({"is_ai_training_opted_in": True})

        html = OrganizationAdmin(Organization, AdminSite()).ai_training_opt_in_history_display(self.organization)

        self.assertIn("Currently opted in", html)
        self.assertIn("opted out → opted in", html)
        self.assertIn(self.user.email, html)

    def test_admin_panel_is_blank_on_the_add_form(self) -> None:
        html = OrganizationAdmin(Organization, AdminSite()).ai_training_opt_in_history_display(Organization())

        self.assertEqual(html, "-")

    def test_changes_to_other_organization_fields_are_excluded(self) -> None:
        self._patch_organization({"name": "Renamed org"})
        self._patch_organization({"is_ai_data_processing_approved": False})

        history = get_ai_training_opt_in_history(self.organization)

        self.assertEqual(history.changes, [])
