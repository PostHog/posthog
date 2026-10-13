from uuid import uuid4

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog import redis
from posthog.models import Organization, OrganizationMembership, Team

from products.access_control.backend.facade.contracts import AuthorizationRule
from products.authz.backend.facade import api
from products.authz.backend.facade.contracts import CheckRequest, Context, Resource, Subject
from products.authz.backend.facade.enums import Action, ResourceType
from products.authz.backend.logic import authorization, sync_state, synchronization
from products.authz.backend.logic.synchronization import OrganizationProjection, Relationship


class TestOrganizationProjection(SimpleTestCase):
    @parameterized.expand(
        [
            ("project", "member", "direct_member"),
            ("project", "none", "direct_none"),
            ("dashboard", "viewer", "direct_viewer"),
            ("insight", "manager", "direct_manager"),
        ]
    )
    def test_individual_assignments_use_direct_relations(self, resource: str, level: str, relation: str) -> None:
        organization = Organization(id=uuid4())
        membership = OrganizationMembership(id=uuid4(), organization=organization, user_id=1)
        team = Team(id=1, organization=organization)
        rule = AuthorizationRule(
            resource=resource,
            resource_id=str(team.id) if resource == "project" else None,
            access_level=level,
            organization_member_id=membership.id,
            role_id=None,
        )
        with (
            patch.object(Organization.objects, "filter") as organizations,
            patch.object(Organization, "is_feature_available", return_value=True),
            patch.object(OrganizationMembership.objects, "filter", return_value=[membership]),
            patch.object(Team.objects, "filter", return_value=[team]),
            patch.object(synchronization, "authorization_roles", return_value=[]),
            patch.object(synchronization, "authorization_rules", return_value=[rule]),
            patch.object(synchronization, "authorization_dashboards", return_value=[]),
            patch("products.product_analytics.backend.facade.api.authorization_insights", return_value=[]),
        ):
            organizations.return_value.first.return_value = organization
            relationships = OrganizationProjection(organization.id).build()

        target = (
            f"project:{organization.id}/{team.id}"
            if resource == "project"
            else f"access_policy:{organization.id}/{team.id}/{resource}/default"
        )
        assignments = {
            relationship
            for relationship in relationships
            if relationship.object == target and relationship.user.endswith("#user")
        }
        assert assignments == {
            Relationship(
                user=f"organization_member:{organization.id}/{membership.id}#user",
                relation=relation,
                object=target,
            )
        }


class TestAuthorizationFailures(SimpleTestCase):
    def setUp(self) -> None:
        self.organization_id = uuid4()
        self.resource = Resource(type=ResourceType.ORGANIZATION, id=str(self.organization_id))
        self.subject = Subject(user_id=1)
        self.pending = sync_state.mark_pending(self.organization_id)
        sync_state.mark_ready(self.organization_id, self.pending)

    def tearDown(self) -> None:
        redis.get_client().delete(sync_state.state_key(self.organization_id))

    @patch("products.authz.backend.logic.authorization.get_openfga_client")
    def test_pending_reconciliation_denies_without_consulting_stale_grants(self, get_client: MagicMock) -> None:
        sync_state.mark_pending(self.organization_id)
        assert not authorization.check(
            [CheckRequest(resource=self.resource, action=Action.VIEW, subject=self.subject)], None
        )[0]
        get_client.assert_not_called()

    @patch("products.authz.backend.logic.authorization.get_openfga_client")
    def test_error_is_not_an_allow_or_a_fallback(self, get_client: MagicMock) -> None:
        error = RuntimeError("Authorization service unavailable")
        get_client.return_value.client_batch_check.side_effect = error
        with self.assertRaises(RuntimeError):
            authorization.check([CheckRequest(resource=self.resource, action=Action.VIEW, subject=self.subject)], None)
        get_client.return_value.close.assert_called_once()

    @patch("products.authz.backend.logic.authorization.get_openfga_client")
    def test_commit_during_check_invalidates_the_old_decision(self, get_client: MagicMock) -> None:
        def commit(*args: object, **kwargs: object) -> list[MagicMock]:
            sync_state.mark_pending(self.organization_id)
            sync_state.mark_ready(self.organization_id, self.pending)
            return [MagicMock(allowed=True, error=None)]

        get_client.return_value.client_batch_check.side_effect = commit
        assert not authorization.check(
            [CheckRequest(resource=self.resource, action=Action.VIEW, subject=self.subject)], None
        )[0]

    def test_context_and_principals_are_not_silently_ignored(self) -> None:
        with self.assertRaises(ValueError):
            api.check(resource=self.resource, action=Action.VIEW)
        with self.assertRaises(NotImplementedError):
            api.check(resource=self.resource, action=Action.VIEW, subject=Subject(api_key_id="example"))
        with self.assertRaises(NotImplementedError):
            api.check(
                resource=self.resource, action=Action.VIEW, subject=self.subject, context=Context(channel="example")
            )
