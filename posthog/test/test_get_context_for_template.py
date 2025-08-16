from unittest.mock import MagicMock

from posthog.utils import get_context_for_template
from django.test import SimpleTestCase


class TestGetContextForTemplate(SimpleTestCase):
    def test_get_context_for_template(self):
        with self.settings(STRIPE_PUBLIC_KEY=None):
            actual = get_context_for_template(
                MagicMock(),
            )

        assert actual == {
            "git_rev": "1a4241c9f7",
            "js_capture_time_to_see_data": False,
            "js_kea_verbose_logging": False,
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
