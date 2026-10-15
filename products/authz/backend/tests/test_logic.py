from uuid import uuid4

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog import redis

from products.access_control.backend.facade.user_access_control import RESOURCE_INHERITANCE_MAP
from products.authz.backend.facade import api
from products.authz.backend.facade.contracts import CheckRequest, Context, Resource, Subject
from products.authz.backend.facade.enums import Action, ResourceType
from products.authz.backend.logic import authorization, sync_state


class TestResourceKeys(SimpleTestCase):
    @parameterized.expand(list(RESOURCE_INHERITANCE_MAP.items()))
    def test_inherited_categories_use_the_parent_policy(self, child: str, parent: str) -> None:
        organization_id = uuid4()
        for project_id in (1, 2):
            resource = Resource(type=ResourceType(child), project_id=project_id)
            assert authorization.object_key(resource, org_id=organization_id) == (
                f"resource:{organization_id}/{project_id}/{parent}"
            )
        with self.assertRaises(ValueError):
            authorization.object_key(Resource(type=ResourceType(child)), org_id=organization_id)
        if child == "warehouse_table":
            id = str(uuid4())
            assert (
                authorization.object_key(
                    Resource(type=ResourceType(child), id=id, project_id=1), org_id=organization_id
                )
                == f"warehouse_table:{organization_id}/1/{id}"
            )
        else:
            with self.assertRaises(NotImplementedError):
                authorization.object_key(
                    Resource(type=ResourceType(child), id="123", project_id=1), org_id=organization_id
                )


class TestAuthorizationFailures(SimpleTestCase):
    def setUp(self) -> None:
        self.organization_id = uuid4()
        self.resource = Resource(type=ResourceType.ORGANIZATION, id=str(self.organization_id))
        self.subject = Subject(user_id=1)
        self.pending = sync_state.mark_pending(self.organization_id)
        sync_state.mark_ready(self.organization_id, self.pending)

    def tearDown(self) -> None:
        redis.get_client().delete(sync_state.state_key(self.organization_id))

    @parameterized.expand([("pending", None), ("old_projection", b"ready:old-projection")])
    @patch("products.authz.backend.logic.authorization.pooled_openfga_client")
    def test_pending_reconciliation_denies_without_consulting_stale_grants(
        self, _name: str, old_state: bytes | None, get_client: MagicMock
    ) -> None:
        if old_state is None:
            sync_state.mark_pending(self.organization_id)
        else:
            redis.get_client().set(sync_state.state_key(self.organization_id), old_state)
        assert not authorization.check(
            [CheckRequest(resource=self.resource, action=Action.VIEW, subject=self.subject)], None
        )[0]
        get_client.assert_not_called()

    @patch("products.authz.backend.logic.authorization.pooled_openfga_client")
    def test_error_is_not_an_allow_or_a_fallback(self, get_client: MagicMock) -> None:
        error = RuntimeError("Authorization service unavailable")
        get_client.return_value.__enter__.return_value.client_batch_check.side_effect = error
        with self.assertRaises(RuntimeError):
            authorization.check([CheckRequest(resource=self.resource, action=Action.VIEW, subject=self.subject)], None)
        get_client.return_value.__exit__.assert_called_once()

    @patch("products.authz.backend.logic.authorization.pooled_openfga_client")
    def test_commit_during_check_invalidates_the_old_decision(self, get_client: MagicMock) -> None:
        def commit(*args: object, **kwargs: object) -> list[MagicMock]:
            sync_state.mark_pending(self.organization_id)
            sync_state.mark_ready(self.organization_id, self.pending)
            return [MagicMock(allowed=True, error=None)]

        get_client.return_value.__enter__.return_value.client_batch_check.side_effect = commit
        assert not authorization.check(
            [CheckRequest(resource=self.resource, action=Action.VIEW, subject=self.subject)], None
        )[0]

    @parameterized.expand([("default", None, "HIGHER_CONSISTENCY"), ("cached", "MINIMIZE_LATENCY", "MINIMIZE_LATENCY")])
    @patch("products.authz.backend.logic.authorization.pooled_openfga_client")
    def test_enforcement_consistency_and_explicit_cached_checks(
        self, _name: str, consistency: str | None, expected: str, get_client: MagicMock
    ) -> None:
        client = get_client.return_value.__enter__.return_value
        client.client_batch_check.return_value = [MagicMock(allowed=True, error=None)]
        requests = [CheckRequest(resource=self.resource, action=Action.VIEW, subject=self.subject)]
        if consistency is None:
            assert authorization.check(requests, None) == [True]
        else:
            assert authorization.check(requests, None, consistency="MINIMIZE_LATENCY") == [True]
        assert client.client_batch_check.call_args.args[1] == {"consistency": expected}

    def test_context_and_principals_are_not_silently_ignored(self) -> None:
        with self.assertRaises(ValueError):
            api.check(resource=self.resource, action=Action.VIEW)
        with self.assertRaises(NotImplementedError):
            api.check(resource=self.resource, action=Action.VIEW, subject=Subject(api_key_id="example"))
        with self.assertRaises(NotImplementedError):
            api.check(
                resource=self.resource, action=Action.VIEW, subject=self.subject, context=Context(channel="example")
            )
