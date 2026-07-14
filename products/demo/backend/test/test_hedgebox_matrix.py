import uuid
import datetime as dt
from types import SimpleNamespace
from typing import Any, cast

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from products.data_tools.backend.models.join import DataWarehouseJoin
from products.demo.backend.logic.matrix.models import SimEvent
from products.demo.backend.logic.products.hedgebox.matrix import HedgeboxMatrix
from products.demo.backend.logic.products.hedgebox.taxonomy import (
    EVENT_DOWNGRADED_PLAN,
    EVENT_PAID_BILL,
    EVENT_SIGNED_UP,
    EVENT_UPGRADED_PLAN,
    EVENT_UPLOADED_FILE,
)
from products.warehouse_sources.backend.facade.models import (
    DataWarehouseCredential,
    DataWarehouseTable,
    WarehouseColumnAnnotation,
)


class TestHedgeboxMatrixDemoWarehouseTables(SimpleTestCase):
    def test_collect_demo_data_warehouse_rows(self):
        matrix = HedgeboxMatrix(seed="warehouse-test", n_clusters=0)
        matrix.is_complete = True

        matrix.clusters = [  # ty: ignore[invalid-assignment]
            SimpleNamespace(
                people=[
                    SimpleNamespace(
                        past_events=[
                            self._make_event(
                                EVENT_PAID_BILL,
                                "person-1",
                                dt.datetime(2025, 1, 4, 12, 0, tzinfo=dt.UTC),
                                {"amount_usd": 49.0, "plan": "business_standard"},
                            ),
                            self._make_event(
                                EVENT_SIGNED_UP,
                                "person-2",
                                dt.datetime(2025, 1, 1, 8, 30, tzinfo=dt.UTC),
                                {"from_invite": True},
                            ),
                            self._make_event(
                                EVENT_UPLOADED_FILE,
                                "person-3",
                                dt.datetime(2025, 1, 2, 9, 15, tzinfo=dt.UTC),
                                {"file_type": "pdf", "file_size_b": 2048, "used_mb": 12.5},
                            ),
                            self._make_event(
                                EVENT_DOWNGRADED_PLAN,
                                "person-4",
                                dt.datetime(2025, 1, 5, 13, 0, tzinfo=dt.UTC),
                                {"previous_plan": "business_pro", "new_plan": "business_standard"},
                            ),
                            self._make_event(
                                EVENT_UPGRADED_PLAN,
                                "person-4",
                                dt.datetime(2025, 1, 3, 11, 0, tzinfo=dt.UTC),
                                {"previous_plan": "personal_free", "new_plan": "business_standard"},
                            ),
                        ]
                    )
                ]
            )  # type: ignore[list-item]
        ]

        table_specs = {table_spec.name: table_spec for table_spec in matrix._demo_data_warehouse_table_specs()}

        assert matrix._collect_demo_data_warehouse_rows(table_specs["paid_bills"]) == [
            (1, "person-1", "2025-01-04 12:00:00", 49.0, "business_standard")
        ]
        assert matrix._collect_demo_data_warehouse_rows(table_specs["signups"]) == [
            (1, "person-2", "2025-01-01 08:30:00", True)
        ]
        assert matrix._collect_demo_data_warehouse_rows(table_specs["uploaded_files"]) == [
            (1, "person-3", "2025-01-02 09:15:00", "pdf", 2048, 12.5, "")
        ]
        assert matrix._collect_demo_data_warehouse_rows(table_specs["plan_changes"]) == [
            (1, "person-4", "2025-01-03 11:00:00", "upgrade", "personal_free", "business_standard"),
            (2, "person-4", "2025-01-05 13:00:00", "downgrade", "business_pro", "business_standard"),
        ]

    def test_collect_demo_extended_person_rows(self):
        matrix = HedgeboxMatrix(seed="warehouse-test", n_clusters=0)
        matrix.is_complete = True

        matrix.clusters = [  # ty: ignore[invalid-assignment]
            SimpleNamespace(
                people=[
                    SimpleNamespace(
                        in_product_id="biz-user",
                        properties_at_now={"email": "owner@acme.test"},
                        account=SimpleNamespace(
                            team_members={"biz-user", "coworker-user"},
                            files={"a", "b", "c", "d", "e"},
                            current_used_mb=512.0,
                            allocation_used_fraction=0.64,
                            current_monthly_bill_usd=40.0,
                            plan="business/standard",
                        ),
                        cluster=SimpleNamespace(company=SimpleNamespace(name="Acme", industry="technology")),
                        name="Owner Name",
                        onboarding_variant="blue",
                        file_engagement_variant="red",
                        watches_marius_tech_tips=True,
                        is_invitable=False,
                    ),
                    SimpleNamespace(
                        in_product_id="solo-user",
                        properties_at_now={"email": "solo@example.test"},
                        account=SimpleNamespace(
                            team_members={"solo-user"},
                            files=set(),
                            current_used_mb=0.0,
                            allocation_used_fraction=0.0,
                            current_monthly_bill_usd=0.0,
                            plan="personal/free",
                        ),
                        cluster=SimpleNamespace(company=None),
                        name="Solo User",
                        onboarding_variant="control",
                        file_engagement_variant="blue",
                        watches_marius_tech_tips=False,
                        is_invitable=True,
                    ),
                    SimpleNamespace(
                        in_product_id="visitor-user",
                        properties_at_now={},
                        account=None,
                        cluster=SimpleNamespace(company=None),
                        name="Visitor User",
                        onboarding_variant="red",
                        file_engagement_variant="control",
                        watches_marius_tech_tips=False,
                        is_invitable=True,
                    ),
                ]
            )  # type: ignore[list-item]
        ]

        assert matrix._collect_demo_extended_person_rows() == [
            (
                1,
                "owner@acme.test",
                "biz-user",
                "Acme",
                "technology",
                "business",
                "business/standard",
                2,
                5,
                512.0,
                0.64,
                40.0,
                "power_user",
                "blue",
                "red",
                True,
                False,
            ),
            (
                2,
                "solo@example.test",
                "solo-user",
                "Solo User",
                "consumer",
                "personal",
                "personal/free",
                1,
                0,
                0.0,
                0.0,
                0.0,
                "signed_up",
                "control",
                "blue",
                False,
                True,
            ),
        ]

    @patch("products.demo.backend.logic.products.hedgebox.matrix.object_storage.write")
    @patch("products.demo.backend.logic.products.hedgebox.matrix.DataWarehouseTable.objects.create")
    @patch("products.demo.backend.logic.products.hedgebox.matrix.DataWarehouseTable.objects.filter")
    def test_upsert_demo_data_warehouse_table_sets_csv_double_quotes_on_create(
        self, mock_filter, mock_create, _mock_write
    ):
        matrix = HedgeboxMatrix(seed="warehouse-test", n_clusters=0)
        team = cast(Any, SimpleNamespace(pk=1))
        user = cast(Any, SimpleNamespace())
        credential = object()

        mock_filter.return_value.first.return_value = None

        matrix._upsert_demo_data_warehouse_table_contents(
            team=team,
            user=user,
            credential=credential,
            table_name="extended_properties",
            columns={"email": "String", "company_name": "String"},
            rows=[("owner@acme.test", "Acme, Inc.")],
        )

        mock_create.assert_called_once()
        assert mock_create.call_args.kwargs["options"] == {"csv_allow_double_quotes": True}

    @patch("products.demo.backend.logic.products.hedgebox.matrix.object_storage.write")
    @patch("products.demo.backend.logic.products.hedgebox.matrix.DataWarehouseTable.objects.filter")
    def test_upsert_demo_data_warehouse_table_sets_csv_double_quotes_on_update(self, mock_filter, _mock_write):
        matrix = HedgeboxMatrix(seed="warehouse-test", n_clusters=0)
        team = cast(Any, SimpleNamespace(pk=1))
        user = cast(Any, SimpleNamespace())
        credential = object()
        existing_table = SimpleNamespace(
            external_data_source=None,
            options={},
            created_by_id=None,
            save=MagicMock(),
        )

        mock_filter.return_value.first.return_value = existing_table

        matrix._upsert_demo_data_warehouse_table_contents(
            team=team,
            user=user,
            credential=credential,
            table_name="extended_properties",
            columns={"email": "String", "company_name": "String"},
            rows=[("owner@acme.test", "Acme, Inc.")],
        )

        assert existing_table.options == {"csv_allow_double_quotes": True}
        existing_table.save.assert_called_once()

    @staticmethod
    def _make_event(event: str, distinct_id: str, timestamp: dt.datetime, properties: dict) -> SimEvent:
        return SimEvent(
            event=event,
            distinct_id=distinct_id,
            properties=properties,
            timestamp=timestamp,
            person_id=uuid.uuid4(),
            person_properties={},
            person_created_at=timestamp,
        )


@override_settings(
    OBJECT_STORAGE_ACCESS_KEY_ID="warehouse-access-key",
    OBJECT_STORAGE_SECRET_ACCESS_KEY="warehouse-access-secret",
    OBJECT_STORAGE_BUCKET="warehouse-bucket",
)
class TestHedgeboxMatrixDemoWarehouseClone(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.target_team = self.organization.teams.create(name="Warehouse clone target")
        self.source_credential = DataWarehouseCredential.objects.create(
            team=self.team,
            access_key="warehouse-access-key",
            access_secret="warehouse-access-secret",
        )
        self.source_tables = self._create_source_warehouse()

    def test_clone_creates_isolated_metadata_for_the_target_team(self) -> None:
        HedgeboxMatrix.clone_demo_data_warehouse(self.team, self.target_team, self.user)

        target_tables = list(DataWarehouseTable.raw_objects.filter(team=self.target_team).order_by("name"))
        assert [table.name for table in target_tables] == sorted(HedgeboxMatrix.DEMO_DATA_WAREHOUSE_TABLE_NAMES)
        assert {table.credential_id for table in target_tables} != {self.source_credential.id}
        assert len({table.credential_id for table in target_tables}) == 1
        assert target_tables[0].credential is not None
        assert target_tables[0].credential.team_id == self.target_team.id

        source_tables_by_name = {table.name: table for table in self.source_tables}
        for target_table in target_tables:
            source_table = source_tables_by_name[target_table.name]
            assert target_table.id != source_table.id
            assert target_table.url_pattern == source_table.url_pattern
            assert target_table.columns == source_table.columns
            assert target_table.column_order == source_table.column_order
            assert target_table.options == source_table.options
            assert target_table.row_count == source_table.row_count
            assert target_table.size_in_s3_mib == source_table.size_in_s3_mib

        target_annotations = list(WarehouseColumnAnnotation.objects.for_team(self.target_team.id).all())
        assert len(target_annotations) == 1
        assert target_annotations[0].table.team_id == self.target_team.id
        assert target_annotations[0].column_name == "amount_usd"
        assert target_annotations[0].description == "Amount paid in US dollars"

        target_join = DataWarehouseJoin.objects.get(team=self.target_team)
        assert target_join.source_table_name == "persons"
        assert target_join.source_table_key == "properties.email"
        assert target_join.joining_table_name == HedgeboxMatrix.DEMO_DATA_WAREHOUSE_EXTENDED_PROPERTIES_TABLE
        assert target_join.joining_table_key == "email"
        assert target_join.field_name == HedgeboxMatrix.DEMO_DATA_WAREHOUSE_EXTENDED_PROPERTIES_TABLE
        assert target_join.configuration == {"type": "left"}

        assert DataWarehouseTable.raw_objects.filter(team=self.team).count() == len(
            HedgeboxMatrix.DEMO_DATA_WAREHOUSE_TABLE_NAMES
        )
        assert DataWarehouseJoin.objects.filter(team=self.team).count() == 1

    @parameterized.expand([("missing_table",), ("missing_join",)])
    def test_clone_rejects_an_incomplete_source_without_writing_target_metadata(self, missing_part: str) -> None:
        if missing_part == "missing_table":
            self.source_tables[0].delete()
        else:
            DataWarehouseJoin.objects.filter(team=self.team).delete()

        with self.assertRaises(RuntimeError):
            HedgeboxMatrix.clone_demo_data_warehouse(self.team, self.target_team, self.user)

        assert not DataWarehouseTable.raw_objects.filter(team=self.target_team).exists()
        assert not DataWarehouseCredential.objects.filter(team=self.target_team).exists()
        assert not DataWarehouseJoin.objects.filter(team=self.target_team).exists()
        assert not WarehouseColumnAnnotation.objects.for_team(self.target_team.id).exists()

    @patch("products.demo.backend.logic.products.hedgebox.matrix.object_storage.head_object")
    def test_readiness_requires_every_master_csv(self, mock_head_object: MagicMock) -> None:
        mock_head_object.return_value = {}
        assert HedgeboxMatrix.demo_data_warehouse_is_ready(self.team)

        missing_key = HedgeboxMatrix._demo_data_warehouse_object_key(
            HedgeboxMatrix.DEMO_DATA_WAREHOUSE_SIGNUPS_TABLE, self.team.id
        )
        mock_head_object.side_effect = lambda *, file_key, bucket: None if file_key == missing_key else {}
        assert not HedgeboxMatrix.demo_data_warehouse_is_ready(self.team)

    def _create_source_warehouse(self) -> list[DataWarehouseTable]:
        tables = [
            DataWarehouseTable.objects.create(
                team=self.team,
                name=table_name,
                format=DataWarehouseTable.TableFormat.CSVWithNames,
                url_pattern=f"https://warehouse.test/master/{table_name}/*.csv",
                queryable_folder=f"master/{table_name}",
                credential=self.source_credential,
                columns={"id": "Int64", "value": "String"},
                column_order=["id", "value"],
                options={"csv_allow_double_quotes": True},
                row_count=10,
                size_in_s3_mib=1.5,
                created_by=self.user,
            )
            for table_name in HedgeboxMatrix.DEMO_DATA_WAREHOUSE_TABLE_NAMES
        ]
        paid_bills_table = next(
            table for table in tables if table.name == HedgeboxMatrix.DEMO_DATA_WAREHOUSE_PAID_BILLS_TABLE
        )
        WarehouseColumnAnnotation.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            table=paid_bills_table,
            column_name="amount_usd",
            description="Amount paid in US dollars",
            description_source=WarehouseColumnAnnotation.DescriptionSource.CANONICAL,
            ai_model="warehouse-test-model",
        )
        DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name="persons",
            source_table_key="properties.email",
            joining_table_name=HedgeboxMatrix.DEMO_DATA_WAREHOUSE_EXTENDED_PROPERTIES_TABLE,
            joining_table_key="email",
            field_name=HedgeboxMatrix.DEMO_DATA_WAREHOUSE_EXTENDED_PROPERTIES_TABLE,
            configuration={"type": "left"},
        )
        return tables


class TestHedgeboxMatrixDemoOAuthApplication(SimpleTestCase):
    @parameterized.expand(
        [
            ("local_dev", "dummy-key", True, False, False),
            ("cloud_prod", "dummy-key", False, True, True),
            ("self_hosted_prod", "dummy-key", False, False, True),
            ("debug_but_cloud", "dummy-key", True, True, True),
            ("no_oidc_key", "", True, False, True),
        ]
    )
    @patch("products.demo.backend.logic.products.hedgebox.matrix.OAuthApplication.objects.create")
    def test_demo_oauth_app_only_created_in_local_dev(
        self,
        _name: str,
        oidc_key: str,
        debug: bool,
        cloud: bool,
        should_skip: bool,
        mock_create: MagicMock,
    ) -> None:
        matrix = HedgeboxMatrix(seed="oauth-test", n_clusters=0)
        team = cast(Any, SimpleNamespace(organization=SimpleNamespace()))
        user = cast(Any, SimpleNamespace())

        with override_settings(OIDC_RSA_PRIVATE_KEY=oidc_key, DEBUG=debug):
            with patch("products.demo.backend.logic.products.hedgebox.matrix.is_cloud", return_value=cloud):
                matrix._set_up_demo_oauth_application(team, user)

        if should_skip:
            mock_create.assert_not_called()
        else:
            mock_create.assert_called_once()
            kwargs = mock_create.call_args.kwargs
            assert kwargs["is_first_party"] is True
            assert "example.com" not in kwargs["redirect_uris"]
