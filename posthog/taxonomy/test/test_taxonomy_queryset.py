from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models import EventDefinition, EventProperty, PropertyDefinition


class TestTaxonomyQuerySet(SimpleTestCase):
    @parameterized.expand(
        [
            ("property_definition", PropertyDefinition, "posthog_propertydefinition"),
            ("event_definition", EventDefinition, "posthog_eventdefinition"),
            ("event_property", EventProperty, "posthog_eventproperty"),
        ]
    )
    def test_for_project_filters_on_the_indexed_project_key(self, _name: str, model, table: str) -> None:
        # Each table's unique index leads with COALESCE(project_id, team_id). A rewrite to a plain team_id
        # predicate still returns the rows of a single-environment project, so only the SQL shows the seek is lost.
        sql = str(model.objects.for_project(42).query)

        self.assertIn(f'COALESCE("{table}"."project_id", "{table}"."team_id") = 42', sql)
        self.assertNotIn(f'"{table}"."team_id" = ', sql)
