import io

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from products.dashboards.backend.api.dashboard_template_json_schema_parser import (
    DashboardTemplateCreationJSONSchemaParser,
)


class TestDashboardTemplateCreationJSONSchemaParser(SimpleTestCase):
    @parameterized.expand(
        [
            ("list", b"[]"),
            ("bool", b"true"),
            ("string", b'"a template"'),
            ("number", b"1"),
            ("null", b"null"),
            ("object_without_template", b"{}"),
        ]
    )
    def test_body_that_is_not_an_object_with_a_template_raises_validation_error(self, _name: str, body: bytes) -> None:
        with self.assertRaises(ValidationError):
            DashboardTemplateCreationJSONSchemaParser().parse(io.BytesIO(body))
