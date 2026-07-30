from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Any

from posthog.test.base import APIBaseTest, BaseTest, NonAtomicBaseTest
from unittest.mock import patch

from django.db import IntegrityError, close_old_connections, transaction
from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status
from rest_framework.exceptions import ValidationError

from posthog.hogql.database.lazy_join_tags import DATA_WAREHOUSE_EXPERIMENTS
from posthog.hogql.errors import QueryError

from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value
from posthog.rate_limit import HogQLQueryThrottle

from products.data_catalog.backend.facade.enums import RelationshipStatus
from products.data_catalog.backend.logic import relationships
from products.data_catalog.backend.logic.exceptions import CatalogConflict
from products.data_catalog.backend.logic.relationships import accept_proposal, propose_relationship, reject_proposal
from products.data_catalog.backend.models import RelationshipProposal
from products.data_catalog.backend.presentation.serializers import RelationshipProposalSerializer
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

    def test_equivalent_key_formatting_is_deduped(self) -> None:
        propose_relationship(team=self.team, user=self.user, **_JOIN)
        with self.assertRaises(CatalogConflict):
            propose_relationship(
                team=self.team,
                user=self.user,
                **{**_JOIN, "source_table_key": " distinct_id ", "joining_table_key": " id "},
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

    def test_physical_field_name_collision_rejected(self) -> None:
        proposal = propose_relationship(team=self.team, user=self.user, **{**_JOIN, "field_name": "timestamp"})
        with patch.object(relationships, "execute_hogql_query"):
            with self.assertRaises(ValidationError):
                accept_proposal(proposal, self.user)

    def test_builtin_lazy_field_name_collision_rejected(self) -> None:
        proposal = propose_relationship(team=self.team, user=self.user, **{**_JOIN, "field_name": "group_0"})
        with patch.object(relationships, "execute_hogql_query"):
            with self.assertRaises(ValidationError):
                accept_proposal(proposal, self.user)

    def test_experiments_optimized_probe_uses_experiments_resolver(self) -> None:
        # An experiments-optimized events join resolves through DATA_WAREHOUSE_EXPERIMENTS at query
        # time; the probe must build it the same way so an invalid experiments_timestamp_key is caught
        # during review instead of the plain equality resolver silently passing it.
        proposal = propose_relationship(
            team=self.team,
            user=self.user,
            source_table_name="persons",
            source_table_key="id",
            joining_table_name="events",
            joining_table_key="person_id",
            field_name="linked_events",
            configuration={"experiments_optimized": True, "experiments_timestamp_key": "timestamp"},
        )
        captured: dict[str, str] = {}

        def _capture(**kwargs: Any) -> None:
            database = kwargs["context"].database
            captured["resolver"] = database.get_table("persons").fields["_catalog_probe"].resolver

        with patch.object(relationships, "execute_hogql_query", side_effect=_capture):
            accept_proposal(proposal, self.user)

        assert captured["resolver"] == DATA_WAREHOUSE_EXPERIMENTS

    @parameterized.expand([("empty_dict", {}), ("null", None)])
    def test_exact_existing_join_is_reused(self, _name: str, configuration: dict[str, Any] | None) -> None:
        join = DataWarehouseJoin.objects.create(team=self.team, configuration=configuration, **_JOIN)
        proposal = self._propose()
        with patch.object(relationships, "execute_hogql_query"):
            accepted = accept_proposal(proposal, self.user)

        assert accepted.created_join_id == join.id
        assert DataWarehouseJoin.objects.filter(team_id=self.team.id, field_name=_JOIN["field_name"]).count() == 1


class TestRejectProposal(BaseTest):
    def test_reject_persists_reason(self) -> None:
        proposal = propose_relationship(team=self.team, user=self.user, **_JOIN)
        rejected = reject_proposal(proposal, self.user, "wrong keys")
        assert rejected.status == RelationshipStatus.REJECTED
        assert rejected.rejection_reason == "wrong keys"

    def test_accepted_proposal_cannot_be_rejected(self) -> None:
        proposal = propose_relationship(team=self.team, user=self.user, **_JOIN)
        with patch.object(relationships, "execute_hogql_query"):
            accepted = accept_proposal(proposal, self.user)

        with self.assertRaises(ValidationError):
            reject_proposal(accepted, self.user, "changed my mind")

        accepted.refresh_from_db()
        assert accepted.status == RelationshipStatus.ACCEPTED
        assert accepted.created_join_id is not None
        assert DataWarehouseJoin.objects.filter(pk=accepted.created_join_id, deleted=False).exists()


class TestRelationshipConcurrency(NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def _run_concurrently(self, operations: list[str], proposal_ids: list[str]) -> list[str]:
        barrier = Barrier(len(operations))

        def run(operation: str, proposal_id: str) -> str:
            close_old_connections()
            try:
                proposal = RelationshipProposal.objects.for_team(self.team.id).get(pk=proposal_id)
                barrier.wait()
                if operation == "accept":
                    accept_proposal(proposal, None)
                else:
                    reject_proposal(proposal, None, "not valid")
                return operation
            except ValidationError:
                return "validation_error"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=len(operations)) as executor:
            futures = [
                executor.submit(run, operation, proposal_id)
                for operation, proposal_id in zip(operations, proposal_ids, strict=True)
            ]
            return [future.result() for future in futures]

    def test_concurrent_accept_and_reject_leave_consistent_state(self) -> None:
        proposal = propose_relationship(team=self.team, user=self.user, **_JOIN)
        with patch.object(relationships, "execute_hogql_query"):
            results = self._run_concurrently(["accept", "reject"], [str(proposal.id), str(proposal.id)])

        proposal.refresh_from_db()
        assert results.count("validation_error") == 1
        assert proposal.status in {RelationshipStatus.ACCEPTED, RelationshipStatus.REJECTED}
        assert DataWarehouseJoin.objects.filter(team_id=self.team.id, field_name=_JOIN["field_name"]).count() == (
            1 if proposal.status == RelationshipStatus.ACCEPTED else 0
        )

    def test_concurrent_accepts_with_same_accessor_create_one_join(self) -> None:
        first = propose_relationship(team=self.team, user=self.user, **_JOIN)
        second = propose_relationship(
            team=self.team,
            user=self.user,
            **{**_JOIN, "source_table_key": "uuid", "joining_table_key": "created_at"},
        )
        with patch.object(relationships, "execute_hogql_query"):
            results = self._run_concurrently(["accept", "accept"], [str(first.id), str(second.id)])

        assert results.count("accept") == 1
        assert results.count("validation_error") == 1
        assert DataWarehouseJoin.objects.filter(team_id=self.team.id, field_name=_JOIN["field_name"]).count() == 1


class TestRelationshipProposalSerializer(SimpleTestCase):
    @parameterized.expand([(0.0,), (1.0,)])
    def test_confidence_boundaries_are_valid(self, confidence: float) -> None:
        serializer = RelationshipProposalSerializer(data={**_JOIN, "confidence": confidence})
        assert serializer.is_valid(), serializer.errors

    @parameterized.expand([(-0.01,), (1.01,)])
    def test_confidence_outside_range_is_invalid(self, confidence: float) -> None:
        serializer = RelationshipProposalSerializer(data={**_JOIN, "confidence": confidence})
        assert not serializer.is_valid()
        assert "confidence" in serializer.errors


class TestRelationshipAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.url = f"/api/projects/{self.team.id}/data_catalog/relationship_proposals/"

    def test_create_proposal(self) -> None:
        response = self.client.post(self.url, _JOIN, format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert response.json()["status"] == RelationshipStatus.PROPOSED

    def test_create_proposal_rejects_invalid_confidence(self) -> None:
        response = self.client.post(self.url, {**_JOIN, "confidence": 1.01}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_create_proposal_rejects_malformed_join_key(self) -> None:
        response = self.client.post(self.url, {**_JOIN, "source_table_key": "("}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @parameterized.expand(
        [
            (
                "without_approval_scope",
                ["data_catalog:read", "data_catalog:write", "query:read"],
                status.HTTP_403_FORBIDDEN,
            ),
            (
                "without_query_scope",
                ["data_catalog:read", "data_catalog:write", "data_catalog_approval:write", "warehouse_view:write"],
                status.HTTP_403_FORBIDDEN,
            ),
            (
                "without_warehouse_view_scope",
                ["data_catalog:read", "data_catalog:write", "data_catalog_approval:write", "query:read"],
                status.HTTP_403_FORBIDDEN,
            ),
            (
                "with_all_scopes",
                [
                    "data_catalog:read",
                    "data_catalog:write",
                    "data_catalog_approval:write",
                    "query:read",
                    "warehouse_view:write",
                ],
                status.HTTP_200_OK,
            ),
        ]
    )
    def test_accept_requires_approval_query_and_warehouse_view_scopes(
        self, _name: str, scopes: list[str], expected_status: int
    ) -> None:
        proposal = propose_relationship(team=self.team, user=self.user, **_JOIN)
        raw = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="k",
            user=self.user,
            secure_value=hash_key_value(raw),
            scopes=scopes,
        )
        self.client.logout()
        with patch.object(relationships, "execute_hogql_query"):
            response = self.client.post(f"{self.url}{proposal.id}/accept/", HTTP_AUTHORIZATION=f"Bearer {raw}")
        assert response.status_code == expected_status

    def test_accept_uses_hogql_query_throttle(self) -> None:
        proposal = propose_relationship(team=self.team, user=self.user, **_JOIN)
        with (
            patch.object(HogQLQueryThrottle, "allow_request", return_value=False),
            patch.object(HogQLQueryThrottle, "wait", return_value=None),
        ):
            response = self.client.post(f"{self.url}{proposal.id}/accept/")
        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS

    def test_reject_via_api(self) -> None:
        proposal = propose_relationship(team=self.team, user=self.user, **_JOIN)
        response = self.client.post(f"{self.url}{proposal.id}/reject/", {"rejection_reason": "nope"}, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["status"] == RelationshipStatus.REJECTED
