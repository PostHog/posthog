from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import connection
from django.test import SimpleTestCase
from django.test.utils import CaptureQueriesContext

from parameterized import parameterized
from structlog.testing import capture_logs

from posthog.models import OrganizationMembership, User

from products.authz.backend.facade import api
from products.authz.backend.facade.contracts import CheckRequest, Resource, ResourceIds, Subject
from products.authz.backend.facade.enums import Action, ResourceType


class TestAuthorizationRollout(SimpleTestCase):
    def setUp(self) -> None:
        self.resource = Resource(type=ResourceType.DASHBOARD, project_id=1, organization_id=uuid4())
        self.subject = Subject(user_id=1)
        organization = patch(
            "products.authz.backend.logic.authorization.organization_id",
            side_effect=lambda resource: resource.organization_id,
        )
        organization.start()
        self.addCleanup(organization.stop)
        guests = patch("products.authz.backend.logic.rollout.guest_memberships", return_value=set())
        guests.start()
        self.addCleanup(guests.stop)

    @parameterized.expand(
        [
            ("v1", "v1", False, True, False),
            ("disabled", False, True, False, True),
            ("missing", None, True, False, True),
            ("boolean", True, False, True, False),
            ("unknown", "unexpected", True, False, True),
            ("shadow_mismatch", "v1-shadow-log", True, False, True),
            ("shadow_match", "v1-shadow-log", False, False, False),
            ("v2_mismatch", "v2", True, False, False),
            ("v2_match", "v2", True, True, True),
        ]
    )
    def test_authoritative_decision_and_comparison(
        self, _name: str, variant: str | bool | None, v1: bool, v2: bool, expected: bool
    ) -> None:
        with (
            patch("products.authz.backend.logic.rollout.get_feature_flag_or_none", return_value=variant),
            patch("products.authz.backend.logic.legacy_authorization.check", return_value=[v1]),
            patch("products.authz.backend.logic.authorization.check", return_value=[v2]) as openfga,
            capture_logs() as logs,
        ):
            assert api.check(resource=self.resource, action=Action.VIEW, subject=self.subject) is expected
        if variant not in ("v1-shadow-log", "v2"):
            openfga.assert_not_called()
            assert not logs
        else:
            assert logs[0]["v1_allowed"] is v1
            assert logs[0]["v2_allowed"] is v2
            assert logs[0]["matches"] is (v1 == v2)

    def test_batch_preserves_order_and_routes_each_organization_separately(self) -> None:
        other = Resource(type=ResourceType.DASHBOARD, project_id=2, organization_id=uuid4())
        requests = [
            CheckRequest(resource=self.resource, action=Action.VIEW, subject=self.subject),
            CheckRequest(resource=other, action=Action.EDIT, subject=self.subject),
            CheckRequest(resource=self.resource, action=Action.EDIT, subject=self.subject),
        ]
        with (
            patch("products.authz.backend.logic.rollout.get_feature_flag_or_none", side_effect=["v1", "v2"]),
            patch("products.authz.backend.logic.legacy_authorization.check", side_effect=[[True, False], [True]]),
            patch("products.authz.backend.logic.authorization.check", return_value=[False]),
        ):
            assert api.check(requests) == [True, False, False]
            assert api.check([]) == []

    @parameterized.expand(
        [
            (f"{variant}_{operation}", variant, operation)
            for variant in ("v1-shadow-log", "v2")
            for operation in ("check", "list_resources")
        ]
    )
    def test_comparison_error_does_not_change_authoritative_decision(
        self, _name: str, variant: str, operation: str
    ) -> None:
        primary = "authorization" if variant == "v2" else "legacy_authorization"
        secondary = "legacy_authorization" if variant == "v2" else "authorization"
        listed = ResourceIds(ids=frozenset({"1"}), complete=True)
        with (
            patch("products.authz.backend.logic.rollout.get_feature_flag_or_none", return_value=variant),
            patch(
                f"products.authz.backend.logic.{primary}.{operation}",
                return_value=[True] if operation == "check" else listed,
            ),
            patch(f"products.authz.backend.logic.{secondary}.{operation}", side_effect=RuntimeError("Unavailable")),
            capture_logs() as logs,
        ):
            if operation == "check":
                assert api.check(resource=self.resource, action=Action.VIEW, subject=self.subject)
            else:
                assert api.list_resources(resource=self.resource, action=Action.VIEW, subject=self.subject) == listed
        assert logs[0]["event"] == ("authz_shadow_check_failed" if operation == "check" else "authz_shadow_list_failed")
        assert logs[1]["matches"] is None

    @parameterized.expand([("v1", "v1"), ("shadow", "v1-shadow-log"), ("v2", "v2")])
    def test_authoritative_errors_propagate_without_fallback(self, _name: str, variant: str) -> None:
        primary = "authorization" if variant == "v2" else "legacy_authorization"
        with (
            patch("products.authz.backend.logic.rollout.get_feature_flag_or_none", return_value=variant),
            patch(f"products.authz.backend.logic.{primary}.check", side_effect=RuntimeError("Unavailable")),
        ):
            with self.assertRaises(RuntimeError):
                api.check(resource=self.resource, action=Action.VIEW, subject=self.subject)

    @parameterized.expand([("shadow", "v1-shadow-log"), ("v2", "v2")])
    def test_mixed_batch_keeps_non_allowlisted_resources_on_v1(self, _name: str, variant: str) -> None:
        other = Resource(type=ResourceType.PROJECT, id="1", organization_id=self.resource.organization_id)
        requests = [
            CheckRequest(resource=other, action=Action.VIEW, subject=self.subject),
            CheckRequest(resource=self.resource, action=Action.VIEW, subject=self.subject),
            CheckRequest(resource=other, action=Action.EDIT, subject=self.subject),
        ]
        with (
            patch("products.authz.backend.logic.rollout.get_feature_flag_or_none", return_value=variant),
            patch(
                "products.authz.backend.logic.legacy_authorization.check",
                side_effect=lambda batch, context: [True for request in batch],
            ),
            patch(
                "products.authz.backend.logic.authorization.check",
                side_effect=lambda batch, context: [
                    False
                    if request.resource.type == ResourceType.DASHBOARD
                    else self.fail("Non-allowlisted resource reached v2")
                    for request in batch
                ],
            ),
        ):
            assert api.check(requests) == [True, variant != "v2", True]
            assert api.permissions(resource=other, subject=self.subject)

    def test_permissions_use_the_routed_decisions(self) -> None:
        with (
            patch("products.authz.backend.logic.rollout.get_feature_flag_or_none", return_value="v1"),
            patch(
                "products.authz.backend.logic.legacy_authorization.check",
                side_effect=lambda requests, context: [request.action == Action.VIEW for request in requests],
            ),
        ):
            assert api.permissions(resource=self.resource, subject=self.subject) == frozenset({Action.VIEW})

    @parameterized.expand([("v1", "v1"), ("shadow", "v1-shadow-log"), ("v2", "v2")])
    def test_lists_use_the_same_rollout_mode(self, _name: str, variant: str) -> None:
        v1 = ResourceIds(ids=frozenset({"1"}), complete=True)
        v2 = ResourceIds(ids=frozenset(), complete=False)
        with (
            patch("products.authz.backend.logic.rollout.get_feature_flag_or_none", return_value=variant),
            patch("products.authz.backend.logic.legacy_authorization.list_resources", return_value=v1),
            patch("products.authz.backend.logic.authorization.list_resources", return_value=v2) as openfga,
            capture_logs() as logs,
        ):
            assert api.list_resources(resource=self.resource, action=Action.VIEW, subject=self.subject) == (
                v2 if variant == "v2" else v1
            )
        if variant == "v1":
            openfga.assert_not_called()
        else:
            assert logs[0]["matches"] is False
            assert logs[0]["v1_complete"] is True
            assert logs[0]["v2_complete"] is False


class TestGuestRollout(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.guest = User.objects.create_and_join(self.organization, "guest@example.com", "test-password")
        OrganizationMembership.objects.filter(user=self.guest).update(level=OrganizationMembership.Level.GUEST)

    def _request(self, resource_type: ResourceType, user: User) -> CheckRequest:
        return CheckRequest(
            resource=Resource(
                type=resource_type,
                id=str(self.team.id) if resource_type == ResourceType.PROJECT else str(uuid4()),
                project_id=self.team.id,
            ),
            action=Action.VIEW,
            subject=Subject(user_id=user.id),
        )

    @parameterized.expand(
        [
            ("guest notebook on v2", "guest", "v2", ResourceType.NOTEBOOK, "v2"),
            ("guest recording on v2", "guest", "v2", ResourceType.SESSION_RECORDING, "v2"),
            ("guest project on v2", "guest", "v2", ResourceType.PROJECT, "v2"),
            ("guest type without guest rules on v2", "guest", "v2", ResourceType.FEATURE_FLAG, "denied"),
            ("guest when the org is not on v2", "guest", None, ResourceType.DASHBOARD, "v1"),
            ("member notebook on v2", "member", "v2", ResourceType.NOTEBOOK, "v1"),
        ]
    )
    def test_guest_checks_route_to_v2_without_a_shadow(
        self, _name: str, who: str, variant: str | None, resource_type: ResourceType, expected: str
    ) -> None:
        user = self.guest if who == "guest" else self.user
        with (
            patch("products.authz.backend.logic.rollout.get_feature_flag_or_none", return_value=variant),
            patch("products.authz.backend.logic.rollout.authorization.check", return_value=[True]) as v2,
            patch("products.authz.backend.logic.rollout.legacy_authorization.check", return_value=[True]) as v1,
        ):
            decisions = api.check([self._request(resource_type, user)])
        assert decisions == [expected != "denied"]
        assert v2.called == (expected == "v2")
        assert v1.called == (expected == "v1")

    def test_a_request_looks_up_guest_memberships_once(self) -> None:
        with (
            patch("products.authz.backend.logic.rollout.get_feature_flag_or_none", return_value="v2"),
            patch("products.authz.backend.logic.rollout.authorization.check", return_value=[True]),
            patch("products.authz.backend.logic.rollout.legacy_authorization.check", return_value=[True]),
            api.authorization_session(),
            CaptureQueriesContext(connection) as queries,
        ):
            for user in (self.user, self.user, self.guest, self.guest):
                api.check([self._request(ResourceType.DASHBOARD, user)])
        assert len([query for query in queries if "posthog_organizationmembership" in query["sql"]]) == 2

    def test_guest_lists_use_v2_without_a_shadow(self) -> None:
        resource = Resource(type=ResourceType.NOTEBOOK, project_id=self.team.id)
        listed = ResourceIds(ids=frozenset({"a"}), complete=True)
        with (
            patch("products.authz.backend.logic.rollout.get_feature_flag_or_none", return_value="v2"),
            patch("products.authz.backend.logic.rollout.authorization.list_resources", return_value=listed) as v2,
            patch("products.authz.backend.logic.rollout.legacy_authorization.list_resources") as v1,
        ):
            result = api.list_resources(resource=resource, action=Action.VIEW, subject=Subject(user_id=self.guest.id))
        assert result == listed
        v2.assert_called_once()
        v1.assert_not_called()
