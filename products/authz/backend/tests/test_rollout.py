from uuid import uuid4

from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized
from structlog.testing import capture_logs

from products.authz.backend.facade import api
from products.authz.backend.facade.contracts import CheckRequest, Resource, ResourceIds, Subject
from products.authz.backend.facade.enums import Action, ResourceType


class TestAuthorizationRollout(SimpleTestCase):
    def setUp(self) -> None:
        self.resource = Resource(type=ResourceType.DASHBOARD, project_id=1, organization_id=uuid4())
        self.subject = Subject(user_id=1)
        organization = patch(
            "products.authz.backend.logic.authorization.organization_id",
            side_effect=lambda resource, **kwargs: resource.organization_id,
        )
        organization.start()
        self.addCleanup(organization.stop)

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
            patch("products.authz.backend.logic.legacy_authorization.list_resources", autospec=True, return_value=v1),
            patch(
                "products.authz.backend.logic.authorization.list_resources", autospec=True, return_value=v2
            ) as openfga,
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
