from posthog.test.base import APIBaseTest
from unittest import mock

from products.data_warehouse.backend.sql_visualization_ai import SQLVisualizationGenerationOutput


class TestSQLVisualization(APIBaseTest):
    def test_create(self):
        with mock.patch(
            "products.data_warehouse.backend.api.sql_visualization.generate_sql_visualization",
            return_value=SQLVisualizationGenerationOutput(
                spec={
                    "data": {"name": "posthog_results"},
                    "mark": "bar",
                    "encoding": {"y": {"field": "count", "type": "quantitative"}},
                },
                explanation="Bar chart by count.",
                warnings=[],
            ),
        ) as generate_sql_visualization:
            response = self.client.post(
                f"/api/projects/{self.team.id}/sql_visualization/",
                {
                    "query": "select count() as count from events",
                    "prompt": "make a chart",
                    "columns": [
                        {
                            "name": "count",
                            "type": "Int64",
                            "semanticType": "quantitative",
                            "sampleValues": [3],
                            "nullCount": 0,
                            "distinctSampleCount": 1,
                        }
                    ],
                    "fields": [
                        {
                            "field": "count",
                            "sourceColumn": "count",
                            "label": "count",
                            "type": "Int64",
                        }
                    ],
                    "sampleRows": [{"count": 3}],
                    "rowCount": 1,
                },
            )

        assert response.status_code == 200
        assert response.json()["trace_id"].startswith("sql_visualization_")
        assert response.json()["spec"]["data"] == {"name": "posthog_results"}
        generate_sql_visualization.assert_called_once()
        assert generate_sql_visualization.call_args.kwargs["payload"]["query"] == "select count() as count from events"

    def test_rejects_missing_columns(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/sql_visualization/",
            {
                "query": "select count() as count from events",
                "prompt": "make a chart",
                "columns": [],
                "sampleRows": [],
                "rowCount": 0,
            },
        )

        assert response.status_code == 400
