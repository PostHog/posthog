from typing import Optional

from posthog.hogql.metadata import get_hogql_metadata
from posthog.models import PropertyDefinition, Cohort
from posthog.schema import HogQLMetadata, HogQLMetadataResponse, HogQLQuery
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from django.test import override_settings


class TestMetadata(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None

    def _expr(self, query: str, table: str = "events", debug=True) -> HogQLMetadataResponse:
        return get_hogql_metadata(
            query=HogQLMetadata(
                kind="HogQLMetadata",
                language="hogQLExpr",
                query=query,
                sourceQuery=HogQLQuery(query=f"select * from {table}"),
                response=None,
                debug=debug,
            ),
            team=self.team,
        )

    def _select(self, query: str) -> HogQLMetadataResponse:
        return get_hogql_metadata(
            query=HogQLMetadata(kind="HogQLMetadata", language="hogQL", query=query, response=None),
            team=self.team,
        )

    def _program(self, query: str, globals: Optional[dict] = None) -> HogQLMetadataResponse:
        return get_hogql_metadata(
            query=HogQLMetadata(kind="HogQLMetadata", language="hog", query=query, globals=globals, response=None),
            team=self.team,
        )

    def _template(self, query: str) -> HogQLMetadataResponse:
        return get_hogql_metadata(
            query=HogQLMetadata(kind="HogQLMetadata", language="hogTemplate", query=query, response=None),
            team=self.team,
        )

    def test_metadata_valid_expr_select(self):
        metadata = self._expr("select 1")
        self.assertEqual(
            metadata.dict(),
            metadata.dict()
            | {
                "isValid": False,
                "query": "select 1",
                "errors": [
                    {
                        "message": "extraneous input '1' expecting <EOF>",
                        "start": 7,
                        "end": 8,
                        "fix": None,
                    }
                ],
            },
        )

        metadata = self._select("select 1")
        self.assertEqual(
            metadata.dict(),
            metadata.dict()
            | {
                "isValid": True,
                "query": "select 1",
                "errors": [],
            },
        )

        metadata = self._expr("timestamp")
        self.assertEqual(
            metadata.dict(),
            metadata.dict()
            | {
                "isValid": True,
                "query": "timestamp",
                "errors": [],
            },
        )

        metadata = self._select("timestamp")
        self.assertEqual(
            metadata.dict(),
            metadata.dict()
            | {
                "isValid": False,
                "query": "timestamp",
                "errors": [
                    {
                        "message": "mismatched input 'timestamp' expecting {SELECT, WITH, '{', '(', '<'}",
                        "start": 0,
                        "end": 9,
                        "fix": None,
                    }
                ],
            },
        )

    def test_metadata_expr_parse_error(self):
        metadata = self._expr("1 as true")
        self.assertEqual(
            metadata.dict(),
            metadata.dict()
            | {
                "isValid": False,
                "query": "1 as true",
                "errors": [
                    {
                        "message": '"true" cannot be an alias or identifier, as it\'s a reserved keyword',
                        "start": 0,
                        "end": 9,
                        "fix": None,
                    }
                ],
            },
        )

    def test_metadata_expr_resolve_error(self):
        metadata = self._expr("1 + no_field")
        self.assertEqual(
            metadata.dict(),
            metadata.dict()
            | {
                "isValid": False,
                "query": "1 + no_field",
                "errors": [
                    {
                        "message": "Unable to resolve field: no_field",
                        "start": 4,
                        "end": 12,
                        "fix": None,
                    }
                ],
            },
        )

    def test_metadata_table(self):
        metadata = self._expr("timestamp", "events")
        self.assertEqual(metadata.isValid, True)

        metadata = self._expr("timestamp", "persons")
        self.assertEqual(metadata.isValid, False)

        metadata = self._expr("is_identified", "events")
        self.assertEqual(metadata.isValid, False)

        metadata = self._expr("is_identified", "persons")
        self.assertEqual(metadata.isValid, True)

    @override_settings(PERSON_ON_EVENTS_OVERRIDE=True, PERSON_ON_EVENTS_V2_OVERRIDE=False)
    def test_metadata_in_cohort(self):
        cohort = Cohort.objects.create(team=self.team, name="cohort_name")
        query = (
            f"select person_id from events where person_id in cohort {cohort.pk} or person_id in cohort '{cohort.name}'"
        )
        metadata = self._select(query)
        self.assertEqual(
            metadata.model_dump(),
            metadata.model_dump()
            | {
                "isValid": True,
                "query": query,
                "notices": [
                    {
                        "message": "Field 'person_id' is of type 'String'",
                        "start": 7,
                        "end": 16,
                        "fix": None,
                    },
                    {
                        "message": f"Cohort #{cohort.pk} can also be specified as '{cohort.name}'",
                        "start": 55,
                        "end": 55 + len(str(cohort.pk)),
                        "fix": f"'{cohort.name}'",
                    },
                    {
                        "message": "Field 'person_id' is of type 'String'",
                        "start": 35,
                        "end": 44,
                        "fix": None,
                    },
                    {
                        "message": f"Searching for cohort by name. Replace with numeric ID {cohort.pk} to protect against renaming.",
                        "start": 79 + len(str(cohort.pk)),
                        "end": 92 + len(str(cohort.pk)),
                        "fix": str(cohort.pk),
                    },
                    {
                        "message": "Field 'person_id' is of type 'String'",
                        "start": 59 + len(str(cohort.pk)),
                        "end": 68 + len(str(cohort.pk)),
                        "fix": None,
                    },
                ],
            },
        )

    def test_metadata_property_type_notice_debug(self):
        try:
            from ee.clickhouse.materialized_columns.analyze import materialize
        except ModuleNotFoundError:
            # EE not available? Assume we're good
            self.assertEqual(1 + 2, 3)
            return
        materialize("events", "number")

        PropertyDefinition.objects.create(team=self.team, name="string", property_type="String")
        PropertyDefinition.objects.create(team=self.team, name="number", property_type="Numeric")
        metadata = self._expr("properties.string || properties.number")
        self.assertEqual(
            metadata.dict(),
            metadata.dict()
            | {
                "isValid": True,
                "query": "properties.string || properties.number",
                "notices": [
                    {
                        "message": "Event property 'string' is of type 'String'. This property is not materialized 🐢.",
                        "start": 11,
                        "end": 17,
                        "fix": None,
                    },
                    {
                        "message": "Event property 'number' is of type 'Float'. This property is materialized ⚡️.",
                        "start": 32,
                        "end": 38,
                        "fix": None,
                    },
                ],
            },
        )

    def test_metadata_property_type_notice_no_debug(self):
        try:
            from ee.clickhouse.materialized_columns.analyze import materialize
        except ModuleNotFoundError:
            # EE not available? Assume we're good
            self.assertEqual(1 + 2, 3)
            return
        materialize("events", "number")

        PropertyDefinition.objects.create(team=self.team, name="string", property_type="String")
        PropertyDefinition.objects.create(team=self.team, name="number", property_type="Numeric")
        metadata = self._expr("properties.string || properties.number", debug=False)
        self.assertEqual(
            metadata.dict(),
            metadata.dict()
            | {
                "isValid": True,
                "query": "properties.string || properties.number",
                "notices": [
                    {
                        "message": "Event property 'string' is of type 'String'.",
                        "start": 11,
                        "end": 17,
                        "fix": None,
                    },
                    {
                        "message": "Event property 'number' is of type 'Float'.",
                        "start": 32,
                        "end": 38,
                        "fix": None,
                    },
                ],
            },
        )

    def test_valid_view(self):
        metadata = self._select("select event AS event FROM events")
        self.assertEqual(
            metadata.dict(),
            metadata.dict()
            | {
                "isValid": True,
                "isValidView": True,
                "query": "select event AS event FROM events",
                "errors": [],
            },
        )

    def test_valid_view_nested_view(self):
        saved_query_response = self.client.post(
            f"/api/projects/{self.team.id}/warehouse_saved_queries/",
            {
                "name": "event_view",
                "query": {
                    "kind": "HogQLQuery",
                    "query": f"select event as event from events LIMIT 100",
                },
            },
        )

        metadata = self._select("select event AS event FROM event_view")

        self.assertEqual(saved_query_response.status_code, 201, saved_query_response.json())
        self.assertEqual(
            metadata.dict(),
            metadata.dict()
            | {
                "isValid": True,
                "isValidView": True,
                "query": "select event AS event FROM event_view",
                "errors": [],
            },
        )

    def test_union_all_does_not_crash(self):
        metadata = self._select("SELECT events.event FROM events UNION ALL SELECT events.event FROM events WHERE 1 = 2")
        self.assertEqual(
            metadata.dict(),
            metadata.dict()
            | {
                "isValid": True,
                "errors": [],
            },
        )

    def test_hog_program(self):
        metadata = self._program("let i := 3")
        self.assertEqual(
            metadata.dict(),
            metadata.dict()
            | {
                "isValid": True,
                "errors": [],
            },
        )

    def test_hog_program_invalid(self):
        metadata = self._program("let i := NONO()")
        self.assertEqual(
            metadata.dict(),
            metadata.dict()
            | {
                "query": "let i := NONO()",
                "isValid": False,
                "isValidView": False,
                "notices": [],
                "warnings": [],
                "errors": [{"end": 15, "fix": None, "message": "Hog function `NONO` is not implemented", "start": 9}],
            },
        )

    def test_hog_program_globals(self):
        metadata = self._program("print(event, region)", globals={"event": "banana"})
        self.assertEqual(
            metadata.dict(),
            metadata.dict()
            | {
                "query": "print(event, region)",
                "isValid": True,
                "isValidView": False,
                "notices": [{"end": 11, "fix": None, "message": "Global variable: event", "start": 6}],
                "warnings": [{"end": 19, "fix": None, "message": "Unknown global variable: region", "start": 13}],
                "errors": [],
            },
        )

    def test_string_template(self):
        metadata = self._program("this is a {event} string")
        self.assertEqual(
            metadata.dict(),
            metadata.dict()
            | {
                "isValid": True,
                "errors": [],
            },
        )

    def test_string_template_invalid(self):
        metadata = self._program("this is a {NONO()} string")
        self.assertEqual(
            metadata.dict(),
            metadata.dict()
            | {
                "isValid": False,
                "errors": [{"end": 17, "fix": None, "message": "Hog function `NONO` is not implemented", "start": 11}],
            },
        )
