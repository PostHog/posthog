import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.temporal.ai.slack_app.activities.classifiers import classify_slack_app_project_route
from posthog.temporal.ai.slack_app.posthog_code_slack_mention import POSTHOG_CODE_SLACK_MENTION_TIMEOUT_SECONDS


def _project(*, team_id: int, integration_id: int, name: str) -> Integration:
    """An unsaved `Integration` row, which is all the classifier reads."""
    return Integration(
        id=integration_id,
        kind="slack",
        team=Team(id=team_id, name=name, organization=Organization(name="Northwind")),
    )


# Team ids and integration ids differ so a case fails if the two are ever swapped.
STAGING = _project(team_id=41, integration_id=410, name="Staging")
PRODUCTION = _project(team_id=42, integration_id=420, name="Production")
PROJECTS = [STAGING, PRODUCTION]

CLASSIFIER = "posthog.temporal.ai.slack_app.activities.classifiers.build_openai_client"


class TestClassifySlackAppProjectRoute:
    @parameterized.expand(
        [
            ("named_project", '{"project_id": 41}', STAGING),
            ("no_project", '{"project_id": null}', None),
            ("field_missing", "{}", None),
            # An id outside the offered list is a hallucination or a project this
            # mentioner cannot open. Either way it must not route a run into its data.
            ("unoffered_project", '{"project_id": 99}', None),
            ("fenced_json", '```json\n{"project_id": 42}\n```', PRODUCTION),
            ("empty_reply", "", None),
            ("prose_reply", "I think they mean staging.", None),
            ("wrong_type", '{"project_id": "staging"}', None),
        ]
    )
    def test_resolves_to_an_offered_project(self, _name, content, expected):
        assert self._classify(content) == expected

    def test_llm_failure_propagates_rather_than_reading_as_no_route(self):
        # The eval suite calls this function directly. A swallowed gateway failure is
        # indistinguishable from a clean "no project", so an outage would score as a pass
        # on every negative case and report a healthy mean. The activity does the falling
        # back; this must not.
        with patch(CLASSIFIER, side_effect=RuntimeError("boom")), pytest.raises(RuntimeError):
            classify_slack_app_project_route("check staging", PROJECTS)

    def test_token_cap_uses_the_reasoning_model_parameter(self):
        # `gpt-5.6-luna` rejects `max_tokens` on chat completions, and the activity turns
        # that rejection into its fallback — a mention would silently never route.
        fake_client = self._fake_client('{"project_id": null}')
        with patch(CLASSIFIER, return_value=fake_client):
            classify_slack_app_project_route("check staging", PROJECTS)

        kwargs = fake_client.chat.completions.create.call_args.kwargs
        assert "max_tokens" not in kwargs
        assert kwargs["max_completion_tokens"] > 0

    def test_reply_is_pinned_to_the_offered_projects(self):
        # The enum is the only thing that keeps the classifier from naming a team this
        # mentioner cannot reach. `routable_projects` bounds the list by access, and that
        # bound only reaches the model through this field.
        fake_client = self._fake_client('{"project_id": null}')
        with patch(CLASSIFIER, return_value=fake_client):
            classify_slack_app_project_route("check staging", PROJECTS)

        schema = fake_client.chat.completions.create.call_args.kwargs["response_format"]["json_schema"]
        assert schema["strict"] is True
        assert schema["schema"]["properties"]["project_id"]["enum"] == [41, 42, None]

    def test_call_is_bounded_so_a_slow_gateway_falls_back(self):
        # The gateway client's own defaults are a 600s read and two retries. Unbounded,
        # the activity's deadline expires first, so the mention fails outright instead of
        # taking the fallback this classifier is built around.
        fake_client = self._fake_client('{"project_id": null}')
        with patch(CLASSIFIER, return_value=fake_client):
            classify_slack_app_project_route("check staging", PROJECTS)

        options = fake_client.with_options.call_args.kwargs
        assert options["timeout"] < POSTHOG_CODE_SLACK_MENTION_TIMEOUT_SECONDS
        assert options["max_retries"] * options["timeout"] < POSTHOG_CODE_SLACK_MENTION_TIMEOUT_SECONDS

    def test_default_heads_the_list_and_is_named_by_id(self):
        prompt = self._prompt_for(PROJECTS, PRODUCTION)

        assert self._offered(prompt)[0] == "• `42` — Northwind · Production"
        assert "answered from `42`" in prompt

    def test_no_default_leaves_the_order_alone_and_says_nothing(self):
        prompt = self._prompt_for(PROJECTS, None)

        assert self._offered(prompt)[0] == "• `41` — Northwind · Staging"
        assert "already going to be answered from" not in prompt

    def test_a_team_named_like_the_marker_cannot_pose_as_the_default(self):
        # Team names are tenant text and may be anything, so a name is never the place to
        # put a marker on. The default is named by id, away from the list.
        impostor = _project(team_id=43, integration_id=430, name="Production (default)")
        prompt = self._prompt_for([STAGING, impostor], STAGING)

        assert self._offered(prompt) == [
            "• `41` — Northwind · Staging",
            "• `43` — Northwind · Production (default)",
        ]
        assert "answered from `41`" in prompt

    def test_a_default_outside_the_candidates_is_not_offered(self):
        # The list and the reply schema's enum have to name the same projects, and the
        # enum is built from the candidates alone.
        outsider = _project(team_id=44, integration_id=440, name="Elsewhere")
        fake_client = self._fake_client('{"project_id": null}')
        with patch(CLASSIFIER, return_value=fake_client):
            classify_slack_app_project_route("check staging", PROJECTS, outsider)

        kwargs = fake_client.chat.completions.create.call_args.kwargs
        assert "Elsewhere" not in kwargs["messages"][0]["content"]
        assert "already going to be answered from" not in kwargs["messages"][0]["content"]
        assert kwargs["response_format"]["json_schema"]["schema"]["properties"]["project_id"]["enum"] == [41, 42, None]

    def _prompt_for(self, projects: list[Integration], default: Integration | None) -> str:
        fake_client = self._fake_client('{"project_id": null}')
        with patch(CLASSIFIER, return_value=fake_client):
            classify_slack_app_project_route("check staging", projects, default)
        return fake_client.chat.completions.create.call_args.kwargs["messages"][0]["content"]

    def _offered(self, prompt: str) -> list[str]:
        return [line for line in prompt.splitlines() if line.startswith("• ")]

    def test_prompt_snapshot_matches(self, snapshot):
        """The prompt is the whole classifier — the projects it offers, the
        where-to-look versus what-to-change examples, and the reply contract. Pinning it
        means a reworded rule shows up as a reviewable diff in the ``.ambr`` snapshot
        rather than as a silent behaviour change. Update intentionally by re-running with
        ``--snapshot-update`` after auditing the diff.
        """
        fake_client = self._fake_client('{"project_id": null}')
        with patch(CLASSIFIER, return_value=fake_client):
            classify_slack_app_project_route("how many signups on staging yesterday", PROJECTS, PRODUCTION)
        assert fake_client.chat.completions.create.call_args.kwargs["messages"][0]["content"] == snapshot

    def _fake_client(self, content: str) -> MagicMock:
        response = MagicMock()
        response.choices = [MagicMock(message=MagicMock(content=content))]
        client = MagicMock()
        # `with_options` returns a configured copy, so the fake hands back itself to keep
        # one set of call records no matter how the call site bounds the client.
        client.with_options.return_value = client
        client.chat.completions.create.return_value = response
        return client

    def _classify(self, content: str):
        with patch(CLASSIFIER, return_value=self._fake_client(content)):
            return classify_slack_app_project_route("check staging", PROJECTS)
