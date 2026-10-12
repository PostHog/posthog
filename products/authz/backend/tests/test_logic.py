from uuid import uuid4

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from posthog import redis

from products.authz.backend.facade import api
from products.authz.backend.facade.contracts import Context, Resource, Subject
from products.authz.backend.facade.enums import Action, ResourceType
from products.authz.backend.logic import sync_state


class TestAuthorizationFailures(SimpleTestCase):
    def setUp(self) -> None:
        flag = patch("products.authz.backend.logic.rollout.get_feature_flag_or_none", return_value="v2")
        flag.start()
        self.addCleanup(flag.stop)
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
        assert not api.check(resource=self.resource, action=Action.VIEW, subject=self.subject)
        get_client.assert_not_called()

    @patch("products.authz.backend.logic.authorization.get_openfga_client")
    def test_error_is_not_an_allow_or_a_fallback(self, get_client: MagicMock) -> None:
        error = RuntimeError("Authorization service unavailable")
        get_client.return_value.client_batch_check.side_effect = error
        with self.assertRaises(RuntimeError):
            api.check(resource=self.resource, action=Action.VIEW, subject=self.subject)
        get_client.return_value.close.assert_called_once()

    @patch("products.authz.backend.logic.authorization.get_openfga_client")
    def test_commit_during_check_invalidates_the_old_decision(self, get_client: MagicMock) -> None:
        def commit(*args: object, **kwargs: object) -> list[MagicMock]:
            sync_state.mark_pending(self.organization_id)
            sync_state.mark_ready(self.organization_id, self.pending)
            return [MagicMock(allowed=True, error=None)]

        get_client.return_value.client_batch_check.side_effect = commit
        assert not api.check(resource=self.resource, action=Action.VIEW, subject=self.subject)

    def test_context_and_principals_are_not_silently_ignored(self) -> None:
        with self.assertRaises(ValueError):
            api.check(resource=self.resource, action=Action.VIEW)
        with self.assertRaises(NotImplementedError):
            api.check(resource=self.resource, action=Action.VIEW, subject=Subject(api_key_id="example"))
        with self.assertRaises(NotImplementedError):
            api.check(
                resource=self.resource, action=Action.VIEW, subject=self.subject, context=Context(channel="example")
            )
