from posthog.test.base import BaseTest

from django.urls import reverse

from parameterized import parameterized

from posthog.admin import register_all_admin

from products.data_catalog.backend.facade.api import upsert_metric
from products.data_quality.backend.facade.enums import CheckType, SubjectType, SuiteRunTrigger
from products.data_quality.backend.facade.models import DataQualityCheck, DataQualitySuiteRun

register_all_admin()


class TestDataQualityAdmin(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)
        metric = upsert_metric(
            team=self.team,
            user=self.user,
            name="orders",
            description="Order count",
            definition={"kind": "HogQLQuery", "query": "SELECT 1 AS orders"},
        )
        suite_run = DataQualitySuiteRun.objects.for_team(self.team.id).create(
            team=self.team, trigger=SuiteRunTrigger.MANUAL
        )
        check = DataQualityCheck.objects.for_team(self.team.id).create(
            team=self.team,
            subject_type=SubjectType.METRIC,
            metric_id=metric.id,
            subject_name="orders",
            check_type=CheckType.CUSTOM_SQL,
            fingerprint="a" * 64,
        )
        self.objects = {
            "dataqualitycheck": check,
            "dataqualitysuiterun": suite_run,
        }

    @parameterized.expand([("dataqualitycheck", "metric"), ("dataqualitysuiterun", None)])
    def test_staff_can_render_lists_and_forms_without_a_team_scope(
        self, model_name: str, scoped_field: str | None
    ) -> None:
        for action in ("changelist", "add", "change"):
            with self.subTest(action=action):
                url = reverse(
                    f"admin:data_quality_{model_name}_{action}",
                    args=[self.objects[model_name].pk] if action == "change" else None,
                )
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)

                if action == "change" and scoped_field:
                    related_id = getattr(self.objects[model_name], f"{scoped_field}_id")
                    field = response.context["adminform"].form.fields[scoped_field]
                    self.assertEqual(field.clean(related_id).pk, related_id)

    @parameterized.expand([("dataqualitycheck",)])
    def test_staff_can_save_changes_without_a_team_scope(self, model_name: str) -> None:
        instance = self.objects[model_name]
        payload = {"team": self.team.id, "subject_type": SubjectType.METRIC, "enabled": "on"}
        if isinstance(instance, DataQualityCheck):
            payload.update(
                metric=str(instance.metric_id),
                subject_name=instance.subject_name,
                subject_status=instance.subject_status,
                check_type=instance.check_type,
                severity=instance.severity,
                created_source=instance.created_source,
                description="Check the order count",
                config="{}",
                tags="[]",
            )

        response = self.client.post(reverse(f"admin:data_quality_{model_name}_change", args=[instance.pk]), payload)

        self.assertEqual(response.status_code, 302)
        instance.refresh_from_db()
        if isinstance(instance, DataQualityCheck):
            self.assertEqual(instance.description, "Check the order count")
