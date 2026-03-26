import uuid
import datetime as dt
from types import SimpleNamespace
from typing import Any, cast

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from posthog.demo.matrix.models import SimEvent
from posthog.demo.products.hedgebox.matrix import HedgeboxMatrix
from posthog.demo.products.hedgebox.taxonomy import (
    EVENT_DOWNGRADED_PLAN,
    EVENT_PAID_BILL,
    EVENT_SIGNED_UP,
    EVENT_UPGRADED_PLAN,
    EVENT_UPLOADED_FILE,
)


class TestHedgeboxMatrixDemoWarehouseTables(SimpleTestCase):
    def test_collect_demo_data_warehouse_rows(self):
        matrix = HedgeboxMatrix(seed="warehouse-test", n_clusters=0)
        matrix.is_complete = True

        matrix.clusters = [
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

        matrix.clusters = [
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

    @patch("posthog.demo.products.hedgebox.matrix.object_storage.write")
    @patch("posthog.demo.products.hedgebox.matrix.DataWarehouseTable.objects.create")
    @patch("posthog.demo.products.hedgebox.matrix.DataWarehouseTable.objects.filter")
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

    @patch("posthog.demo.products.hedgebox.matrix.object_storage.write")
    @patch("posthog.demo.products.hedgebox.matrix.DataWarehouseTable.objects.filter")
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
