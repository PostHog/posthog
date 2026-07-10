from posthog.test.base import APIBaseTest, BaseTest

from django.db import IntegrityError, transaction

from rest_framework import status

from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.data_catalog.backend.facade.enums import CertificationStatus
from products.data_catalog.backend.logic.certifications import (
    certifications_for_team,
    certify,
    deprecate,
    propose_certification,
    revoke_certification,
)
from products.data_catalog.backend.logic.exceptions import CatalogConflict
from products.data_catalog.backend.models import TableCertification
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.warehouse_sources.backend.facade.models import DataWarehouseTable


def _table(team, name="stripe_customers") -> DataWarehouseTable:
    return DataWarehouseTable.objects.create(name=name, format="Parquet", team=team, url_pattern="s3://bucket/x")


class TestTableCertificationModel(BaseTest):
    def test_requires_exactly_one_target(self) -> None:
        table = _table(self.team)
        view = DataWarehouseSavedQuery.objects.create(team=self.team, name="v", query={"kind": "HogQLQuery"})
        with self.assertRaises(IntegrityError), transaction.atomic():
            TableCertification.objects.for_team(self.team.id).create(team=self.team, table=table, saved_query=view)

    def test_requires_at_least_one_target(self) -> None:
        with self.assertRaises(IntegrityError), transaction.atomic():
            TableCertification.objects.for_team(self.team.id).create(team=self.team)

    def test_one_certification_per_table(self) -> None:
        table = _table(self.team)
        TableCertification.objects.for_team(self.team.id).create(team=self.team, table=table)
        with self.assertRaises(IntegrityError), transaction.atomic():
            TableCertification.objects.for_team(self.team.id).create(team=self.team, table=table)


class TestCertificationLogic(BaseTest):
    def test_propose_by_id_and_name(self) -> None:
        table = _table(self.team)
        by_id = propose_certification(team=self.team, user=self.user, table_id=str(table.id))
        assert by_id.status == CertificationStatus.PROPOSED
        assert by_id.table_id == table.id

    def test_ambiguous_name_returns_candidates(self) -> None:
        _table(self.team, name="dupe")
        _table(self.team, name="dupe")
        with self.assertRaises(CatalogConflict):
            propose_certification(team=self.team, user=self.user, table_name="dupe")

    def test_duplicate_target_conflicts(self) -> None:
        table = _table(self.team)
        propose_certification(team=self.team, user=self.user, table_id=str(table.id))
        with self.assertRaises(CatalogConflict):
            propose_certification(team=self.team, user=self.user, table_id=str(table.id))

    def test_certify_and_deprecate_set_status_and_are_idempotent(self) -> None:
        table = _table(self.team)
        cert = propose_certification(team=self.team, user=self.user, table_id=str(table.id))

        certified = certify(cert, self.user)
        assert certified.status == CertificationStatus.CERTIFIED
        assert certified.certified_by_id == self.user.id
        assert certify(cert, self.user).status == CertificationStatus.CERTIFIED

        assert deprecate(cert, self.user).status == CertificationStatus.DEPRECATED

    def test_revoke_hard_deletes(self) -> None:
        table = _table(self.team)
        cert = propose_certification(team=self.team, user=self.user, table_id=str(table.id))
        revoke_certification(cert, self.user)
        assert not TableCertification.objects.for_team(self.team.id).filter(pk=cert.pk).exists()

    def test_soft_deleted_target_excluded(self) -> None:
        table = _table(self.team)
        propose_certification(team=self.team, user=self.user, table_id=str(table.id))
        assert certifications_for_team(self.team).count() == 1
        table.deleted = True
        table.save()
        assert certifications_for_team(self.team).count() == 0


class TestCertificationAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.url = f"/api/projects/{self.team.id}/data_catalog/certifications/"

    def test_create_and_certify(self) -> None:
        table = _table(self.team)
        created = self.client.post(self.url, {"table_id": str(table.id)}, format="json")
        assert created.status_code == status.HTTP_201_CREATED, created.json()
        cert_id = created.json()["id"]

        certified = self.client.post(f"{self.url}{cert_id}/certify/")
        assert certified.status_code == status.HTTP_200_OK
        assert certified.json()["status"] == CertificationStatus.CERTIFIED

    def test_certify_requires_approval_scope(self) -> None:
        table = _table(self.team)
        cert = propose_certification(team=self.team, user=self.user, table_id=str(table.id))
        raw = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="k",
            user=self.user,
            secure_value=hash_key_value(raw),
            scopes=["data_catalog:read", "data_catalog:write"],
        )
        self.client.logout()
        response = self.client.post(f"{self.url}{cert.id}/certify/", HTTP_AUTHORIZATION=f"Bearer {raw}")
        assert response.status_code == status.HTTP_403_FORBIDDEN
