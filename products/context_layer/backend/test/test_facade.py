from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

import posthog.storage.object_storage as object_storage_module
from posthog.storage.object_storage import UnavailableStorage

from products.context_layer.backend import store
from products.context_layer.backend.facade import api as facade


@override_settings(OBJECT_STORAGE_ENABLED=True)
class TestContextLayerFacade(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        object_storage_module._client = UnavailableStorage()
        self.addCleanup(setattr, object_storage_module, "_client", UnavailableStorage())

    def test_sandbox_env_vars_with_wiki(self) -> None:
        store.initialize_repo(self.organization.id)
        env = facade.sandbox_environment_variables(self.organization.id, self.team.id)
        assert env[facade.MOUNT_PATH_ENV_VAR] == facade.SANDBOX_MOUNT_PATH
        # The project-nested route, because the sandbox run token carries
        # scoped_teams and the org-nested route refuses it.
        assert env[facade.COMMITS_PATH_ENV_VAR] == f"/api/projects/{self.team.id}/context_layer/agent/commits"

    def test_sandbox_env_vars_empty_without_wiki(self) -> None:
        assert facade.sandbox_environment_variables(self.organization.id, self.team.id) == {}

    @patch("products.context_layer.backend.facade.api.posthog_feature_flag_enabled", side_effect=RuntimeError("boom"))
    def test_flag_check_fails_closed(self, _flag) -> None:
        assert facade.is_context_layer_enabled(organization_id=str(self.organization.id), distinct_id="u") is False

    def test_get_sandbox_mount_presigns_current_head(self) -> None:
        config = store.initialize_repo(self.organization.id)
        mount = facade.get_sandbox_mount(self.organization.id)
        assert mount is not None
        assert mount.head_sha == config.head_sha
        assert mount.bundle_url.startswith("http")

    def test_get_sandbox_mount_is_none_without_wiki(self) -> None:
        assert facade.get_sandbox_mount(self.organization.id) is None


class TestSlackChannelPagePath(SimpleTestCase):
    def test_path_is_named_by_channel_id_under_its_project(self) -> None:
        assert facade.slack_channel_page_path(7, "C0456EFGH") == "projects/7/slack-channels/C0456EFGH.md"

    @parameterized.expand(
        [
            ("traversal", "../../areas/x"),
            ("lowercase", "c0456efgh"),
            ("empty", ""),
            ("reserved_word", "AGENTS"),
            ("workspace_id", "T0123ABCD"),
        ]
    )
    def test_rejects_ids_that_are_not_slack_channel_ids(self, _name: str, slack_channel_id: str) -> None:
        with self.assertRaises(facade.InvalidPagePathError):
            facade.slack_channel_page_path(7, slack_channel_id)
