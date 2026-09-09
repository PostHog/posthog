from uuid import UUID, uuid4

from posthog.test.base import BaseTest

from django.db import IntegrityError, transaction

from parameterized import parameterized

from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.data_quality.backend.facade.enums import (
    CheckRunStatus,
    CheckType,
    SubjectStatus,
    SubjectType,
    SuiteRunTrigger,
)
from products.data_quality.backend.models import DataQualityCheck, DataQualityCheckRun, DataQualitySuiteRun
from products.warehouse_sources.backend.facade.models import DataWarehouseTable


class TestDataQualityModels(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.saved_query_id = uuid4()

    def _create_check(self, **kwargs) -> DataQualityCheck:
        defaults = {
            "team": self.team,
            "subject_type": SubjectType.VIEW,
            "saved_query_id": self.saved_query_id,
            "subject_name": "orders",
            "check_type": CheckType.NOT_NULL,
            "column_name": "customer_id",
            "fingerprint": "a" * 64,
        }
        return DataQualityCheck.objects.for_team(self.team.id).create(**{**defaults, **kwargs})

    def test_same_fingerprint_is_rejected_only_within_a_subject(self) -> None:
        self._create_check()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._create_check()
        other_subject = self._create_check(saved_query_id=uuid4(), subject_name="refunds")
        assert other_subject.pk is not None
        table_subject = self._create_check(
            saved_query_id=None, table_id=uuid4(), subject_type=SubjectType.TABLE, subject_name="stripe_charges"
        )
        assert table_subject.pk is not None

    def test_a_deleted_check_frees_its_definition_for_a_new_one(self) -> None:
        # Authoring a definition that was deleted earlier is a new check with its own id and
        # history, not a resurrection of the row the user believes is gone.
        deleted = self._create_check(deleted=True)

        replacement = self._create_check()

        assert replacement.pk != deleted.pk

    def test_orphaned_checks_escape_fingerprint_uniqueness(self) -> None:
        # SET_NULL orphaning must never be blocked by the constraint, even for twin fingerprints.
        self._create_check(saved_query_id=None)
        second = self._create_check(saved_query_id=None)
        assert second.pk is not None

    def test_subject_binding_rejects_contradictory_rows(self) -> None:
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._create_check(table_id=uuid4())
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._create_check(subject_type=SubjectType.TABLE)

    def test_blank_names_coexist_but_set_names_are_unique(self) -> None:
        self._create_check()
        self._create_check(saved_query_id=uuid4(), subject_name="refunds")

        self._create_check(saved_query_id=uuid4(), subject_name="shipments", name="orders_customer_id_not_null")
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._create_check(saved_query_id=uuid4(), subject_name="returns", name="orders_customer_id_not_null")

    @parameterized.expand(
        [
            (SubjectType.VIEW, "saved_query_id"),
            (SubjectType.TABLE, "table_id"),
        ]
    )
    def test_deleting_the_subject_orphans_the_check(self, subject_type, fk_name) -> None:
        subject_id = self._create_subject(subject_type)
        check = self._create_check(**{"subject_type": subject_type, "saved_query_id": None, fk_name: subject_id})

        self._delete_subject(subject_type, subject_id)

        check.refresh_from_db()
        assert getattr(check, fk_name) is None
        assert check.subject_status == SubjectStatus.ORPHANED

    def _create_subject(self, subject_type: SubjectType) -> UUID:
        if subject_type is SubjectType.VIEW:
            return DataWarehouseSavedQuery.objects.create(
                team=self.team, name="orders", query={"kind": "HogQLQuery", "query": "SELECT 1 AS id"}
            ).id
        return DataWarehouseTable.objects.create(
            team=self.team, name="stripe_charges", format=DataWarehouseTable.TableFormat.Parquet, url_pattern=""
        ).id

    def _delete_subject(self, subject_type: SubjectType, subject_id: UUID) -> None:
        model = DataWarehouseSavedQuery if subject_type is SubjectType.VIEW else DataWarehouseTable
        model.objects.filter(id=subject_id).delete()

    def test_run_history_survives_deleting_the_definition(self) -> None:
        check = self._create_check()
        suite_run = DataQualitySuiteRun.objects.for_team(self.team.id).create(
            team=self.team, trigger=SuiteRunTrigger.MANUAL
        )
        run = DataQualityCheckRun.objects.for_team(self.team.id).create(
            team=self.team,
            quality_check=check,
            suite_run=suite_run,
            subject_type=SubjectType.VIEW,
            subject_uuid=self.saved_query_id,
            subject_name="orders",
            check_type=CheckType.NOT_NULL,
            check_fingerprint=check.fingerprint,
            status=CheckRunStatus.FAILED,
            failed_row_count=3,
        )

        check.delete()

        run.refresh_from_db()
        assert run.quality_check_id is None
        assert run.check_fingerprint == "a" * 64
        assert run.failed_row_count == 3
