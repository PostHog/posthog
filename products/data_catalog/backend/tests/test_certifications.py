from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import MagicMock, patch

from django.db import IntegrityError, transaction
from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status
from rest_framework.exceptions import ValidationError

from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.team import Team
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
from products.data_catalog.backend.presentation.serializers import (
    CertificationCreateSerializer,
    CertificationSerializer,
)
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.warehouse_sources.backend.facade.models import DataWarehouseTable, ExternalDataSource


def _table(
    team: Team,
    name: str = "stripe_customers",
    external_data_source: ExternalDataSource | None = None,
) -> DataWarehouseTable:
    return DataWarehouseTable.objects.create(
        name=name,
        format="Parquet",
        team=team,
        url_pattern="s3://bucket/x",
        external_data_source=external_data_source,
    )


def _view(team: Team, name: str = "revenue_view") -> DataWarehouseSavedQuery:
    return DataWarehouseSavedQuery.objects.create(team=team, name=name, query={"kind": "HogQLQuery"})


class TestTableCertificationModel(BaseTest):
    def test_requires_exactly_one_target(self) -> None:
        table = _table(self.team)
        view = DataWarehouseSavedQuery.objects.create(team=self.team, name="v", query={"kind": "HogQLQuery"})
        with self.assertRaises(IntegrityError), transaction.atomic():
            TableCertification.objects.for_team(self.team.id).create(team=self.team, table=table, saved_query=view)

    def test_requires_at_least_one_target(self) -> None:
        with self.assertRaises(IntegrityError), transaction.atomic():
            TableCertification.objects.for_team(self.team.id).create(team=self.team)

    @parameterized.expand([("table",), ("view",)])
    def test_one_certification_per_target(self, target_type: str) -> None:
        target = _table(self.team) if target_type == "table" else _view(self.team)
        target_fields = {"table": target} if target_type == "table" else {"saved_query": target}
        TableCertification.objects.for_team(self.team.id).create(team=self.team, **target_fields)
        with self.assertRaises(IntegrityError), transaction.atomic():
            TableCertification.objects.for_team(self.team.id).create(team=self.team, **target_fields)


class TestCertificationLogic(BaseTest):
    @parameterized.expand(
        [("table_id", "table"), ("table_name", "table"), ("saved_query_id", "view"), ("view_name", "view")]
    )
    def test_propose_by_selector(self, selector: str, target_type: str) -> None:
        target = _table(self.team) if target_type == "table" else _view(self.team)
        selector_value = str(target.id) if selector.endswith("_id") else target.name

        certification = propose_certification(team=self.team, user=self.user, **{selector: selector_value})

        assert certification.status == CertificationStatus.PROPOSED
        assert certification.created_by_id == self.user.id
        assert certification.table_id == (target.id if target_type == "table" else None)
        assert certification.saved_query_id == (target.id if target_type == "view" else None)

    def test_ambiguous_table_name_returns_candidates(self) -> None:
        _table(self.team, name="dupe")
        _table(self.team, name="dupe")
        with self.assertRaises(CatalogConflict):
            propose_certification(team=self.team, user=self.user, table_name="dupe")

    @parameterized.expand([("table_id", "table"), ("saved_query_id", "view")])
    def test_duplicate_target_conflicts(self, selector: str, target_type: str) -> None:
        target = _table(self.team) if target_type == "table" else _view(self.team)
        target_selector = {selector: str(target.id)}
        propose_certification(team=self.team, user=self.user, **target_selector)
        with self.assertRaises(CatalogConflict):
            propose_certification(team=self.team, user=self.user, **target_selector)

    @parameterized.expand(
        [
            ("table_id", "saved_query_id"),
            ("table_id", "table_name"),
            ("table_id", "view_name"),
            ("saved_query_id", "table_name"),
            ("saved_query_id", "view_name"),
            ("table_name", "view_name"),
        ]
    )
    def test_rejects_mixed_selectors(self, first_selector: str, second_selector: str) -> None:
        table = _table(self.team)
        view = _view(self.team)
        selector_values = {
            "table_id": str(table.id),
            "saved_query_id": str(view.id),
            "table_name": table.name,
            "view_name": view.name,
        }

        with self.assertRaisesMessage(ValidationError, "exactly one"):
            propose_certification(
                team=self.team,
                user=self.user,
                **{first_selector: selector_values[first_selector], second_selector: selector_values[second_selector]},
            )

    def test_concurrent_duplicate_conflicts(self) -> None:
        table = _table(self.team)
        winning_certification = TableCertification(team=self.team, table=table)
        certification_queryset = MagicMock()
        certification_queryset.filter.return_value.first.side_effect = [None, winning_certification]
        certification_queryset.create.side_effect = IntegrityError

        with (
            patch.object(TableCertification.objects, "for_team", return_value=certification_queryset),
            self.assertRaises(CatalogConflict),
        ):
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

    @parameterized.expand([("table",), ("view",), ("external_source",)])
    def test_soft_deleted_target_excluded(self, target_type: str) -> None:
        source = None
        if target_type == "external_source":
            source = ExternalDataSource.objects.create(
                team=self.team,
                source_id="stripe",
                connection_id="stripe",
                status=ExternalDataSource.Status.COMPLETED,
                source_type="Stripe",
            )
        target = _view(self.team) if target_type == "view" else _table(self.team, external_data_source=source)
        selector = "saved_query_id" if target_type == "view" else "table_id"
        propose_certification(team=self.team, user=self.user, **{selector: str(target.id)})
        assert certifications_for_team(self.team).count() == 1

        deleted_object = source or target
        deleted_object.deleted = True
        deleted_object.save()

        assert certifications_for_team(self.team).count() == 0

    def test_serializes_mixed_certifications_in_one_query(self) -> None:
        table_certification = propose_certification(team=self.team, user=self.user, table_id=str(_table(self.team).id))
        certify(table_certification, self.user)
        propose_certification(team=self.team, user=self.user, saved_query_id=str(_view(self.team).id))

        with self.assertNumQueries(1):
            serialized = CertificationSerializer(certifications_for_team(self.team), many=True).data

        assert {certification["target_type"] for certification in serialized} == {"table", "view"}
        assert any(certification["certified_by"] is None for certification in serialized)

    def test_proposal_stays_in_the_requested_environment(self) -> None:
        child_team = Team.objects.create(
            organization=self.organization,
            project=self.project,
            parent_team=self.team,
            name="Child environment",
        )
        table = _table(child_team)

        certification = propose_certification(team=child_team, user=self.user, table_id=str(table.id))

        assert certification.team_id == child_team.id
        assert certifications_for_team(child_team).get() == certification
        assert not certifications_for_team(self.team).exists()

    def test_certifications_are_isolated_between_project_environments(self) -> None:
        child_team = Team.objects.create(
            organization=self.organization,
            project=self.project,
            parent_team=self.team,
            name="Child environment",
        )
        parent_certification = propose_certification(
            team=self.team,
            user=self.user,
            table_id=str(_table(self.team, name="parent_table").id),
        )
        child_certification = propose_certification(
            team=child_team,
            user=self.user,
            table_id=str(_table(child_team, name="child_table").id),
        )

        assert list(certifications_for_team(self.team)) == [parent_certification]
        assert list(certifications_for_team(child_team)) == [child_certification]


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

    def test_ambiguous_table_name_returns_409_with_candidates(self) -> None:
        # The conflict must render through the HTTP exception handler — a shape it can't
        # serialize turns every ambiguous propose into a 500 and hides the candidate ids
        # the caller needs to disambiguate.
        first = _table(self.team, name="dupe")
        second = _table(self.team, name="dupe")
        response = self.client.post(self.url, {"table_name": "dupe"}, format="json")
        assert response.status_code == status.HTTP_409_CONFLICT, response.content
        body = response.json()
        assert body["code"] == "catalog_conflict"
        assert "Multiple tables named 'dupe'" in body["detail"]
        assert {c["id"] for c in body["extra"]["candidates"]} == {str(first.id), str(second.id)}

    def test_duplicate_target_returns_409(self) -> None:
        table = _table(self.team)
        assert self.client.post(self.url, {"table_id": str(table.id)}, format="json").status_code == 201
        response = self.client.post(self.url, {"table_id": str(table.id)}, format="json")
        assert response.status_code == status.HTTP_409_CONFLICT, response.content
        body = response.json()
        assert body["code"] == "catalog_conflict"
        assert "already marked" in body["detail"]

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

    def test_revoke_requires_approval_scope(self) -> None:
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

        response = self.client.delete(f"{self.url}{cert.id}/", HTTP_AUTHORIZATION=f"Bearer {raw}")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert TableCertification.objects.for_team(self.team.id).filter(id=cert.id).exists()

    @parameterized.expand([("certify",), ("deprecate",), ("destroy",)])
    def test_approval_actions_require_base_catalog_scope(self, act: str) -> None:
        # data_catalog_approval:write alone must not grant access without base catalog read —
        # required_scopes replaces the viewset default, so the base scope has to be listed too.
        table = _table(self.team)
        cert = propose_certification(team=self.team, user=self.user, table_id=str(table.id))
        raw = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="k",
            user=self.user,
            secure_value=hash_key_value(raw),
            scopes=["data_catalog_approval:write"],
        )
        self.client.logout()

        if act == "destroy":
            response = self.client.delete(f"{self.url}{cert.id}/", HTTP_AUTHORIZATION=f"Bearer {raw}")
        else:
            response = self.client.post(f"{self.url}{cert.id}/{act}/", HTTP_AUTHORIZATION=f"Bearer {raw}")

        assert response.status_code == status.HTTP_403_FORBIDDEN

    @parameterized.expand([("put",), ("patch",)])
    def test_update_methods_not_allowed(self, method: str) -> None:
        table = _table(self.team)
        cert = propose_certification(team=self.team, user=self.user, table_id=str(table.id), notes="original")

        response = getattr(self.client, method)(f"{self.url}{cert.id}/", {"notes": "changed"}, format="json")

        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
        cert.refresh_from_db()
        assert cert.notes == "original"

    def test_rejects_malformed_uuid(self) -> None:
        response = self.client.post(self.url, {"table_id": "not-a-uuid"}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "table_id"


class TestCertificationInputValidation(SimpleTestCase):
    @parameterized.expand([("table_id",), ("saved_query_id",)])
    def test_rejects_malformed_uuid(self, field: str) -> None:
        serializer = CertificationCreateSerializer(data={field: "not-a-uuid"})
        assert not serializer.is_valid()
        assert field in serializer.errors
