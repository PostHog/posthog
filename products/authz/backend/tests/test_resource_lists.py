from types import SimpleNamespace
from uuid import UUID

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from openfga_sdk.client.models import ClientListObjectsRequest
from parameterized import parameterized

from products.authz.backend.facade import api
from products.authz.backend.facade.contracts import Resource, Subject
from products.authz.backend.facade.enums import Action, ResourceType
from products.authz.backend.logic import authorization


class TestOpenFgaResourceLists(SimpleTestCase):
    def setUp(self) -> None:
        self.org_id = UUID(int=1)
        self.resource = Resource(type=ResourceType.DASHBOARD, project_id=1, organization_id=self.org_id)
        self.subject = Subject(user_id=1)
        self.prefix = f"dashboard:{self.org_id}/1/"
        self.fga_client = MagicMock()
        self.enterContext(
            patch("products.authz.backend.logic.authorization.pooled_openfga_client")
        ).return_value.__enter__.return_value = self.fga_client
        self.enterContext(patch("products.authz.backend.logic.authorization.ready_state", return_value=b"ready:1"))
        self.enterContext(patch("products.authz.backend.logic.authorization.organization_id", return_value=self.org_id))
        self.enterContext(patch("products.authz.backend.logic.rollout.get_feature_flag_or_none", return_value="v2"))
        self.legacy = self.enterContext(
            patch("products.authz.backend.logic.legacy_authorization.list_objects", autospec=True)
        )

    def stream(self, ids: list[str]) -> MagicMock:
        stream = MagicMock()
        stream.__iter__.return_value = iter(SimpleNamespace(object=id) for id in ids)
        self.fga_client.streamed_list_objects.return_value = stream
        return stream

    def test_default_allow_excludes_denied_overrides(self) -> None:
        self.fga_client.check.return_value.allowed = True
        self.stream([self.prefix + "1", self.prefix + "2", f"dashboard:{self.org_id}/2/3"])
        self.fga_client.client_batch_check.return_value = [
            SimpleNamespace(allowed=False, error=None),
            SimpleNamespace(allowed=True, error=None),
        ]
        result = api.list_objects(resource=self.resource, action=Action.VIEW, subject=self.subject)
        assert result.complete and result.excluded
        assert not result.allows("1")
        assert result.allows("2") and result.allows("3")

    @parameterized.expand([("grants", False), ("overrides", True)])
    def test_capped_lists_fail_closed_and_close_stream(self, _name: str, category_allowed: bool) -> None:
        self.fga_client.check.return_value.allowed = category_allowed
        stream = self.stream([self.prefix + "1", self.prefix + "2"])
        result = api.list_objects(
            resource=self.resource, action=Action.VIEW, subject=self.subject, limit=1, creator_exempt=True
        )
        assert not result.complete
        assert not result.allows("1", created_by_user_id=1, subject_user_id=1)
        stream.close.assert_called_once()

    def test_project_denial_does_not_gain_a_creator_exemption(self) -> None:
        self.fga_client.check.return_value.allowed = False
        self.stream([])
        result = api.list_objects(resource=self.resource, action=Action.VIEW, subject=self.subject, creator_exempt=True)
        assert not result.allows("1", created_by_user_id=1, subject_user_id=1)

    def test_reconciliation_during_list_invalidates_result(self) -> None:
        self.fga_client.check.return_value.allowed = True
        self.stream([])
        with patch.object(authorization, "ready_state", side_effect=[b"ready:1", b"ready:2"]):
            result = api.list_objects(resource=self.resource, action=Action.VIEW, subject=self.subject)
        assert not result.complete and not result.allows("1")

    def test_share_link_lists_use_fga_without_legacy_shadow(self) -> None:
        self.fga_client.check.return_value.allowed = False
        self.stream([self.prefix + "2"])
        with patch("products.authz.backend.logic.rollout.get_feature_flag_or_none", return_value="v1"):
            result = api.list_objects(resource=self.resource, action=Action.VIEW, subject=Subject(share_link_id=7))
        assert result.complete and result.allows("2") and not result.allows("1")
        assert self.fga_client.streamed_list_objects.call_args.args[0].user == "share_link:7"
        self.legacy.assert_not_called()

    @parameterized.expand([("allowed", True), ("denied", False)])
    def test_warehouse_query_uses_query_permission(self, _name: str, query_allowed: bool) -> None:
        self.fga_client.check.return_value.allowed = True
        table_id = str(UUID(int=3))
        prefix = f"warehouse_table:{self.org_id}/1/"

        def objects(request: ClientListObjectsRequest, options: object) -> MagicMock:
            stream = MagicMock()
            stream.__iter__.return_value = iter(
                [SimpleNamespace(object=prefix + table_id)] if request.relation == "can_query" and query_allowed else []
            )
            return stream

        self.fga_client.streamed_list_objects.side_effect = objects
        with patch("products.authz.backend.logic.rollout.mode", return_value="v2"):
            result = api.list_objects(
                resource=Resource(type=ResourceType.WAREHOUSE_TABLE, project_id=1, organization_id=self.org_id),
                action=Action.QUERY,
                subject=self.subject,
            )
        assert result.complete and result.allows(table_id) is query_allowed
