import threading
from concurrent.futures import Future

from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized
from posthoganalytics.ai.prompts import PromptResult

from posthog.llm import managed_decision_model
from posthog.llm.managed_decision_model import (
    DEFAULT_DECISION_MODEL,
    BackgroundRefresher,
    ManagedDecisionModel,
    model_from_config,
)

NEW_MODEL = "posthog/hogference/jeeves-0.1"


def managed_result(model: str = NEW_MODEL) -> PromptResult:
    return PromptResult(
        source="api", prompt="Emoji search", name="emoji-search-suggestions", version=3, config={"model": model}
    )


class TestBackgroundRefresher(SimpleTestCase):
    def test_a_request_never_waits_for_the_fetch(self) -> None:
        release = threading.Event()
        fetches: list[Future] = []

        def slow_fetch() -> str:
            assert release.wait(timeout=5)
            return "managed"

        refresher = BackgroundRefresher("test-prompt", "bundled", slow_fetch)
        submit = refresher._executor.submit
        with patch.object(refresher._executor, "submit", side_effect=lambda fn: fetches.append(submit(fn))):
            assert refresher.current() == "bundled"
            assert refresher.current() == "bundled"
            release.set()
            fetches[0].result(timeout=5)

            assert refresher.current() == "managed"
            assert len(fetches) == 1

    @parameterized.expand(
        [
            ("first_fetch_fails", [ConnectionError("unavailable")], "bundled"),
            ("later_fetch_fails", ["managed", ConnectionError("unavailable")], "managed"),
        ]
    )
    def test_a_failed_fetch_keeps_the_last_value(self, _name: str, fetches: list, expected: str) -> None:
        results = iter(fetches)

        def fetch() -> str:
            result = next(results)
            if isinstance(result, Exception):
                raise result
            return result

        refresher = BackgroundRefresher("test-prompt", "bundled", fetch)
        for _ in fetches:
            refresher._refresh()

        assert refresher.current() == expected


class TestManagedDecisionModel(SimpleTestCase):
    def setUp(self) -> None:
        managed_decision_model.app_prompts.cache_clear()
        self.addCleanup(managed_decision_model.app_prompts.cache_clear)

    @parameterized.expand(
        [
            ("valid", {"model": NEW_MODEL}, NEW_MODEL),
            ("missing", {}, DEFAULT_DECISION_MODEL),
            ("wrong_type", {"model": 1}, DEFAULT_DECISION_MODEL),
            ("empty", {"model": ""}, DEFAULT_DECISION_MODEL),
            ("whitespace", {"model": "model\nother"}, DEFAULT_DECISION_MODEL),
        ]
    )
    def test_model_config(self, _name: str, config: dict, expected: str) -> None:
        assert model_from_config(config) == expected

    @patch("posthog.llm.managed_decision_model.posthoganalytics.personal_api_key", "phx_test")
    @patch("posthog.llm.managed_decision_model.Prompts")
    def test_every_refresh_reads_the_posthog_project_through_one_sdk_client(self, prompts_class) -> None:
        prompts_class.return_value.get.return_value = managed_result()
        managed = ManagedDecisionModel("emoji-search-suggestions")

        managed._refresher._refresh()
        managed._refresher._refresh()
        assert managed.fetch(version=3) == NEW_MODEL

        assert managed.current() == NEW_MODEL
        prompts_class.assert_called_once_with(
            managed_decision_model.posthoganalytics, capture_errors=True, default_cache_ttl_seconds=0
        )
        get = prompts_class.return_value.get
        get.assert_any_call("emoji-search-suggestions", with_metadata=True, label="production", version=None)
        get.assert_any_call("emoji-search-suggestions", with_metadata=True, label=None, version=3)

    @patch("posthog.llm.managed_decision_model.posthoganalytics.personal_api_key", None)
    @patch("posthog.llm.managed_decision_model.Prompts")
    def test_without_a_personal_key_the_bundled_model_stays(self, prompts_class) -> None:
        managed = ManagedDecisionModel("emoji-search-suggestions")

        managed._refresher._refresh()

        assert managed.current() == DEFAULT_DECISION_MODEL
        with self.assertRaisesRegex(RuntimeError, "version 3 needs POSTHOG_PERSONAL_API_KEY"):
            managed.fetch(version=3)
        prompts_class.assert_not_called()
