import uuid
import datetime as dt
from types import SimpleNamespace

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
