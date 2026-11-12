from dataclasses import asdict

from unittest.mock import patch

from django.test import SimpleTestCase

from products.dashboards.backend.facade import api as dashboards_api
from products.dashboards.backend.facade.contracts import DashboardTemplateDefinition
from products.demo.backend.logic.dashboard_template_seeds import (
    load_dashboard_template_seeds,
    seed_dev_dashboard_templates,
)


class TestSeedDevDashboardTemplates(SimpleTestCase):
    def test_hands_every_seed_field_to_dashboards_and_reports_only_created_templates(self) -> None:
        payloads = load_dashboard_template_seeds()
        already_stored = payloads[0]["template_name"]
        handed: list[DashboardTemplateDefinition] = []

        def create_if_missing(template: DashboardTemplateDefinition) -> bool:
            handed.append(template)
            return template.template_name != already_stored

        with patch.object(dashboards_api, "create_global_template_if_missing", side_effect=create_if_missing):
            created = seed_dev_dashboard_templates()

        assert created == [payload["template_name"] for payload in payloads[1:]]
        assert [
            {key: asdict(template)[key] for key in payload} for template, payload in zip(handed, payloads, strict=True)
        ] == payloads
