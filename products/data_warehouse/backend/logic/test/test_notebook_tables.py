from posthog.test.base import BaseTest

from parameterized import parameterized

from products.data_warehouse.backend.logic.notebook_tables import (
    NotebookTableError,
    build_notebook_table_url_pattern,
    validate_notebook_table_name,
)
from products.warehouse_sources.backend.facade.models import DataWarehouseTable


class TestValidateNotebookTableName(BaseTest):
    @parameterized.expand(
        [
            ("written_by_a_notebook", "scores", True, None),
            ("fresh_name", "fresh_scores", False, None),
            ("bad_characters", "my-scores", False, "starts with a letter"),
            ("posthog_table", "events", False, "already exists"),
            ("another_table", "scores", False, "a notebook didn't create it"),
        ]
    )
    def test_name_rules(self, _name: str, table_name: str, notebook_owned: bool, error: str | None) -> None:
        DataWarehouseTable.objects.create(
            team_id=self.team.id,
            name="scores",
            format="Parquet",
            url_pattern=(
                build_notebook_table_url_pattern(self.team.id, "scores")
                if notebook_owned
                else "https://bucket.example.com/upload.parquet"
            ),
        )
        if error is None:
            validate_notebook_table_name(self.team.id, table_name, self.user.id)
        else:
            with self.assertRaisesRegex(NotebookTableError, error):
                validate_notebook_table_name(self.team.id, table_name, self.user.id)
