from uuid import uuid4

from posthog.test.base import BaseTest

from django.db import IntegrityError, transaction

from products.data_quality.backend.facade.enums import CheckRunStatus, CheckType, SubjectType, SuiteRunTrigger
from products.data_quality.backend.models import DataQualityCheck, DataQualityCheckRun, DataQualitySuiteRun


class TestDataQualityModels(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.subject_uuid = uuid4()

    def _create_check(self, **kwargs) -> DataQualityCheck:
        defaults = {
            "team": self.team,
            "subject_type": SubjectType.VIEW,
            "subject_uuid": self.subject_uuid,
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
        other_subject = self._create_check(subject_uuid=uuid4(), subject_name="refunds")
        assert other_subject.pk is not None

    def test_blank_names_coexist_but_set_names_are_unique(self) -> None:
        self._create_check()
        self._create_check(subject_uuid=uuid4(), subject_name="refunds")

        self._create_check(subject_uuid=uuid4(), subject_name="shipments", name="orders_customer_id_not_null")
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._create_check(subject_uuid=uuid4(), subject_name="returns", name="orders_customer_id_not_null")

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
            subject_uuid=self.subject_uuid,
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
