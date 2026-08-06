import importlib

from posthog.test.base import BaseTest

from django.apps import apps

from parameterized import parameterized

from ee.models.rbac.access_control import AccessControl
from ee.models.rbac.role import Role

migration_module = importlib.import_module("ee.migrations.0054_backfill_llm_playground_access_control")
backfill_llm_playground_access_control = migration_module.backfill_llm_playground_access_control


class TestBackfillLlmPlaygroundAccessControl(BaseTest):
    def _scope_kwargs(self, case):
        role = (
            Role.objects.create(name="Engineering", organization=self.organization) if case == "role_scoped" else None
        )
        return {
            "organization_member": self.organization_membership if case == "member_scoped" else None,
            "role": role,
        }

    @parameterized.expand(
        [
            ("member_scoped",),
            ("role_scoped",),
            ("org_default",),
        ]
    )
    def test_backfills_resource_wide_row(self, case):
        scope_kwargs = self._scope_kwargs(case)

        AccessControl.objects.create(
            team=self.team, resource="llm_analytics", resource_id=None, access_level="none", **scope_kwargs
        )

        backfill_llm_playground_access_control(apps, None)

        backfilled = AccessControl.objects.filter(resource="llm_playground", team=self.team, **scope_kwargs).first()
        assert backfilled is not None
        assert backfilled.access_level == "none"

    def test_does_not_touch_other_resources(self):
        AccessControl.objects.create(
            team=self.team,
            resource="dataset",
            resource_id=None,
            access_level="editor",
            organization_member=self.organization_membership,
        )

        backfill_llm_playground_access_control(apps, None)

        assert not AccessControl.objects.filter(resource="llm_playground").exists()

    def test_ignores_object_scoped_llm_analytics_rows(self):
        AccessControl.objects.create(
            team=self.team,
            resource="llm_analytics",
            resource_id="123",
            access_level="editor",
            organization_member=self.organization_membership,
        )

        backfill_llm_playground_access_control(apps, None)

        assert not AccessControl.objects.filter(resource="llm_playground").exists()

    def test_does_not_overwrite_existing_row(self):
        AccessControl.objects.create(
            team=self.team,
            resource="llm_analytics",
            resource_id=None,
            access_level="editor",
            organization_member=self.organization_membership,
        )
        AccessControl.objects.create(
            team=self.team,
            resource="llm_playground",
            resource_id=None,
            access_level="none",
            organization_member=self.organization_membership,
        )

        backfill_llm_playground_access_control(apps, None)

        rows = AccessControl.objects.filter(resource="llm_playground", organization_member=self.organization_membership)

        assert rows.count() == 1
        row = rows.first()
        assert row is not None
        assert row.access_level == "none"

    @parameterized.expand(
        [
            ("member_scoped",),
            ("role_scoped",),
            ("org_default",),
        ]
    )
    def test_idempotent_on_repeat_run(self, case):
        # organization_member/role are nullable, and Postgres unique constraints treat NULLs as
        # distinct, so the org_default (both-None) case would silently duplicate on a second run
        # if the migration ever stopped looking up the existing row before creating one.
        scope_kwargs = self._scope_kwargs(case)

        AccessControl.objects.create(
            team=self.team, resource="llm_analytics", resource_id=None, access_level="viewer", **scope_kwargs
        )

        backfill_llm_playground_access_control(apps, None)
        backfill_llm_playground_access_control(apps, None)

        rows = AccessControl.objects.filter(resource="llm_playground", team=self.team, **scope_kwargs)
        assert rows.count() == 1
