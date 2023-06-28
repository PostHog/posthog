from posthog.hogql.metadata import get_hogql_metadata
from posthog.models import PropertyDefinition, Cohort
from posthog.schema import HogQLMetadata, HogQLMetadataResponse
from posthog.test.base import APIBaseTest, ClickhouseTestMixin


class TestMetadata(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None

    def _expr(self, query: str) -> HogQLMetadataResponse:
        return get_hogql_metadata(query=HogQLMetadata(expr=query), team=self.team)

    def _select(self, query: str) -> HogQLMetadataResponse:
        return get_hogql_metadata(query=HogQLMetadata(select=query), team=self.team)

    def test_metadata_valid_expr_select(self):
        metadata = self._expr("select 1")
        self.assertEqual(
            metadata.dict(),
            metadata.dict()
            | {
                "isValid": False,
                "inputExpr": "select 1",
                "inputSelect": None,
                "error": "extraneous input '1' expecting <EOF>",
                "errorStart": 7,
                "errorEnd": 8,
            },
        )

        metadata = self._select("select 1")
        self.assertEqual(
            metadata.dict(),
            metadata.dict()
            | {
                "isValid": True,
                "inputExpr": None,
                "inputSelect": "select 1",
                "error": None,
            },
        )

        metadata = self._expr("timestamp")
        self.assertEqual(
            metadata.dict(),
            metadata.dict()
            | {
                "isValid": True,
                "inputExpr": "timestamp",
                "inputSelect": None,
                "error": None,
            },
        )

        metadata = self._select("timestamp")
        self.assertEqual(
            metadata.dict(),
            metadata.dict()
            | {
                "isValid": False,
                "inputExpr": None,
                "inputSelect": "timestamp",
                "error": "mismatched input 'timestamp' expecting {SELECT, WITH, '('}",
                "errorStart": 0,
                "errorEnd": 9,
            },
        )

    def test_metadata_expr_parse_error(self):
        metadata = self._expr("1 as true")
        self.assertEqual(
            metadata.dict(),
            metadata.dict()
            | {
                "isValid": False,
                "inputExpr": "1 as true",
                "inputSelect": None,
                "error": "Alias 'true' is a reserved keyword.",
                "errorStart": 0,
                "errorEnd": 9,
            },
        )

    def test_metadata_expr_resolve_error(self):
        metadata = self._expr("1 + no_field")
        self.assertEqual(
            metadata.dict(),
            metadata.dict()
            | {
                "isValid": False,
                "inputExpr": "1 + no_field",
                "inputSelect": None,
                "error": "Unable to resolve field: no_field",
                "errorStart": 4,
                "errorEnd": 12,
            },
        )

    def test_metadata_in_cohort(self):
        cohort = Cohort.objects.create(team=self.team, name="cohort_name")
        query = (
            f"select person_id from events where person_id in cohort {cohort.pk} or person_id in cohort '{cohort.name}'"
        )
        metadata = self._select(query)
        self.assertEqual(
            metadata.dict(),
            metadata.dict()
            | {
                "isValid": True,
                "inputExpr": None,
                "inputSelect": query,
                "notices": [
                    {
                        "message": f"Cohort #{cohort.pk} can also be specified as '{cohort.name}'",
                        "start": 55,
                        "end": 55 + len(str(cohort.pk)),
                        "fix": f"'{cohort.name}'",
                    },
                    {
                        "message": f"Searching for cohort by name. Replace with numeric id {cohort.pk} to protect against renaming.",
                        "start": 79 + len(str(cohort.pk)),
                        "end": 92 + len(str(cohort.pk)),
                        "fix": str(cohort.pk),
                    },
                ],
            },
        )

    def test_metadata_property_type_notice(self):
        PropertyDefinition.objects.create(team=self.team, name="string", property_type="String")
        PropertyDefinition.objects.create(team=self.team, name="number", property_type="Numeric")
        metadata = self._expr("properties.string || properties.number")
        self.assertEqual(
            metadata.dict(),
            metadata.dict()
            | {
                "isValid": True,
                "inputExpr": "properties.string || properties.number",
                "inputSelect": None,
                "notices": [
                    {
                        "message": "Property 'string' is of type 'String'.",
                        "start": 0,
                        "end": 17,
                        "fix": None,
                    },
                    {
                        "message": "Property 'number' is of type 'Float'.",
                        "start": 21,
                        "end": 38,
                        "fix": None,
                    },
                ],
            },
        )
