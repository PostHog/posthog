from typing import Any

from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import patch

from django.db import IntegrityError, transaction

from rest_framework import status
from rest_framework.exceptions import ValidationError

from posthog.hogql.errors import QueryError

from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.data_catalog.backend.facade.enums import RelationshipStatus
from products.data_catalog.backend.logic import relationships
from products.data_catalog.backend.logic.exceptions import CatalogConflict
from products.data_catalog.backend.logic.relationships import accept_proposal, propose_relationship, reject_proposal
from products.data_catalog.backend.models import RelationshipProposal
from products.data_tools.backend.facade.models import DataWarehouseJoin

# events and persons always exist in the HogQL database, so propose-time existence checks pass.
_JOIN: dict[str, Any] = {
    "source_table_name": "events",
    "source_table_key": "distinct_id",
    "joining_table_name": "persons",
    "joining_table_key": "id",
    "field_name": "linked_person",
}


class TestRelationshipModel(BaseTest):
    def test_undirected_fingerprint_is_unique(self) -> None:
        RelationshipProposal.objects.for_team(self.team.id).create(
            team=self.team, undirected_fingerprint="abc", **_JOIN
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            RelationshipProposal.objects.for_team(self.team.id).create(
                team=self.team, undirected_fingerprint="abc", **_JOIN
            )


class TestProposeRelationship(BaseTest):
    def test_unknown_table_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            propose_relationship(team=self.team, user=self.user, **{**_JOIN, "source_table_name": "made_up_table"})

    def test_reverse_orientation_is_deduped(self) -> None:
        propose_relationship(team=self.team, user=self.user, **_JOIN)
        with self.assertRaises(CatalogConflict):
            propose_relationship(
                team=self.team,
                user=self.user,
                source_table_name="persons",
                source_table_key="id",
                joining_table_name="events",
                joining_table_key="distinct_id",
                field_name="linked_events",
            )


class TestAcceptProposal(BaseTest):
    def _propose(self) -> RelationshipProposal:
        return propose_relationship(team=self.team, user=self.user, **_JOIN)

    def test_accept_creates_one_join_and_is_idempotent(self) -> None:
        proposal = self._propose()
        with patch.object(relationships, "execute_hogql_query"):  # mock the ClickHouse probe boundary
            accepted = accept_proposal(proposal, self.user)
            accept_proposal(proposal, self.user)  # idempotent

        assert accepted.status == RelationshipStatus.ACCEPTED
        assert accepted.created_join_id is not None
        assert DataWarehouseJoin.objects.filter(team_id=self.team.id, source_table_name="events").count() == 1

    def test_broken_join_probe_rejects(self) -> None:
        proposal = self._propose()
        with patch.object(relationships, "execute_hogql_query", side_effect=QueryError("no such column")):
            with self.assertRaises(ValidationError):
                accept_proposal(proposal, self.user)
        proposal.refresh_from_db()
        assert proposal.status == RelationshipStatus.PROPOSED  # not promoted

    def test_field_name_collision_rejected(self) -> None:
        DataWarehouseJoin.objects.create(
            team=self.team,
            source_table_name="events",
            source_table_key="x",
            joining_table_name="other",
            joining_table_key="y",
            field_name="linked_person",
        )
        proposal = self._propose()
        with patch.object(relationships, "execute_hogql_query"):
            with self.assertRaises(ValidationError):
                accept_proposal(proposal, self.user)


class TestRejectProposal(BaseTest):
    def test_reject_persists_reason(self) -> None:
        proposal = propose_relationship(team=self.team, user=self.user, **_JOIN)
        rejected = reject_proposal(proposal, self.user, "wrong keys")
        assert rejected.status == RelationshipStatus.REJECTED
        assert rejected.rejection_reason == "wrong keys"


class TestRelationshipAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.url = f"/api/projects/{self.team.id}/data_catalog/relationship_proposals/"

    def test_create_proposal(self) -> None:
        response = self.client.post(self.url, _JOIN, format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert response.json()["status"] == RelationshipStatus.PROPOSED

    def test_accept_requires_approval_scope(self) -> None:
        proposal = propose_relationship(team=self.team, user=self.user, **_JOIN)
        raw = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="k",
            user=self.user,
            secure_value=hash_key_value(raw),
            scopes=["data_catalog:read", "data_catalog:write"],
        )
        self.client.logout()
        response = self.client.post(f"{self.url}{proposal.id}/accept/", HTTP_AUTHORIZATION=f"Bearer {raw}")
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_reject_via_api(self) -> None:
        proposal = propose_relationship(team=self.team, user=self.user, **_JOIN)
        response = self.client.post(f"{self.url}{proposal.id}/reject/", {"rejection_reason": "nope"}, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["status"] == RelationshipStatus.REJECTED
