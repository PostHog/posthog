from posthog.test.base import BaseTest

from posthog.hogql.context import HogQLContext
from posthog.hogql.printer.utils import prepare_and_print_ast

from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.data_quality.backend.facade.api import compile_check
from products.data_quality.backend.facade.enums import CheckType, SubjectType
from products.data_quality.backend.logic.contracts import SubjectRef
from products.data_quality.backend.logic.staged_audit import build_staged_database
from products.warehouse_sources.backend.models.credential import DataWarehouseCredential
from products.warehouse_sources.backend.models.table import DataWarehouseTable

PUBLISHED_FOLDER = "query_1000000000000"
STAGED_FOLDER = "query_2000000000000"


class TestStagedAudit(BaseTest):
    def _materialized_view(self) -> DataWarehouseSavedQuery:
        credential = DataWarehouseCredential.objects.create(team=self.team, access_key="_key", access_secret="_secret")
        backing_table = DataWarehouseTable.objects.create(
            name="orders",
            team=self.team,
            columns={"customer_id": "String"},
            credential=credential,
            format=DataWarehouseTable.TableFormat.DeltaS3Wrapper,
            url_pattern="http://localhost:19000/bucket/team_1_model_x/modeling/orders",
            queryable_folder=PUBLISHED_FOLDER,
        )
        return DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="orders",
            query={"query": "SELECT 1 AS customer_id"},
            columns={"customer_id": "String"},
            table=backing_table,
            is_materialized=True,
            status=DataWarehouseSavedQuery.Status.COMPLETED,
        )

    def _compiled_check_urls(self, view: DataWarehouseSavedQuery, staged_folder: str) -> list[str]:
        database = build_staged_database(self.team, view.id, staged_folder)
        assert database is not None
        subject = SubjectRef(
            subject_type=SubjectType.VIEW,
            subject_uuid=str(view.id),
            name=view.name,
            queryable_name=view.name,
            exists=True,
        )
        compiled = compile_check(check_type=CheckType.NOT_NULL, subject=subject, column_name="customer_id", config={})
        context = HogQLContext(team_id=self.team.pk, team=self.team, database=database, enable_select_queries=True)
        prepare_and_print_ast(compiled.query, context=context, dialect="clickhouse")
        # S3 urls print as sensitive parameters, so the staged path lands in context values.
        return [str(value) for value in context.values.values()]

    def test_the_audit_reads_the_staged_folder_not_the_published_one(self) -> None:
        view = self._materialized_view()

        urls = self._compiled_check_urls(view, STAGED_FOLDER)

        assert any(STAGED_FOLDER in url for url in urls)
        assert not any(PUBLISHED_FOLDER in url for url in urls)

    def test_a_view_with_no_backing_table_gets_no_override(self) -> None:
        view = DataWarehouseSavedQuery.objects.create(
            team=self.team,
            name="orders",
            query={"query": "SELECT 1 AS customer_id"},
            columns={"customer_id": "String"},
        )

        assert build_staged_database(self.team, view.id, STAGED_FOLDER) is None
