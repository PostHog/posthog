from posthog.test.base import APIBaseTest
from unittest import mock
from unittest.mock import MagicMock

from posthog.utils import get_context_for_template


class TestGetContextForTemplate(APIBaseTest):
    def test_get_context_for_template(self):
        with self.settings(STRIPE_PUBLIC_KEY=None):
            actual = get_context_for_template(
                MagicMock(),
            )

        # the current team has an api_token
        assert self.team.api_token != "sTMFPsFhdP1Ssg"
        # but we use the posthog cloud api_token for the context
        assert actual == {
            "git_rev": mock.ANY,
            "js_capture_time_to_see_data": False,
            "js_kea_verbose_logging": False,
            # TODO: this is probably not what we should have here in a dev instance
            "js_posthog_api_key": "sTMFPsFhdP1Ssg",
            "js_posthog_host": "",
            "js_posthog_ui_host": "",
            "js_url": "http://localhost:8234",
            "opt_out_capture": False,
            "posthog_app_context": '{"persisted_feature_flags": ["simplify-actions", '
            '"historical-exports-v2", '
            '"ingestion-warnings-enabled", "persons-hogql-query", '
            '"datanode-concurrency-limit", '
            '"session-table-property-filters", "query-async", '
            '"artificial-hog"], "anonymous": false}',
            "posthog_bootstrap": "{}",
            "posthog_js_uuid_version": "v7",
            "region": None,
            "self_capture": True,
        }

    def test_picks_up_stripe_public_key_from_environment(self):
        with self.settings(STRIPE_PUBLIC_KEY="pk_test_12345"):
            actual = get_context_for_template(
                MagicMock(),
            )

        assert actual["stripe_public_key"] == "pk_test_12345"
