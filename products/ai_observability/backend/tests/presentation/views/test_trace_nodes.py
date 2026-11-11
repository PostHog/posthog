import json

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized

from products.ai_observability.backend.models.parser_recipe import ParserRecipe

from .trace_fixtures import ANSWER, GENERATION, QUESTION, create_node_trace, encode_segment, restrict_property


def _tool_call_answer(arguments: str) -> list[dict[str, object]]:
    return [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "f", "arguments": arguments}}],
        }
    ]


DEEP_TOOL_CALL_ANSWER = _tool_call_answer("[" * 300 + "]" * 300)
TICKET = {"ticket_id": "T-42", "summary": "Refund requested"}
TICKET_RECIPE = """
rules:
  - on:
      ticket_id: { exists: true }
      summary: { is: string }
    emit:
      role: system
      content: 'Ticket $.ticket_id: $.summary'
"""


class TestTraceNodeView(ClickhouseTestMixin, APIBaseTest):
    def _url(self, trace_id: str, node_segment: str) -> str:
        return f"/api/projects/{self.team.id}/ai_observability/traces/{encode_segment(trace_id)}/nodes/{node_segment}/"

    def test_returns_the_event_identity_without_its_raw_properties(self) -> None:
        create_node_trace(self.team)

        response = self.client.get(self._url("trace-1", encode_segment(GENERATION)))

        assert response.status_code == 200, response.content
        body = response.json()
        assert (body["id"], body["kind"], body["error"]) == (GENERATION, "generation", None)
        assert body["metadata"]["provider"] == "openai"
        assert set(body["event"]) == {"name", "uuid", "timestamp"}
        assert body["event"]["uuid"] == GENERATION

    @parameterized.expand(
        [
            ("conversation", ANSWER, "messages"),
            ("tool call arguments nested past the bound", DEEP_TOOL_CALL_ANSWER, "json"),
            (
                "tool call arguments with an integer past 64 bits",
                _tool_call_answer('{"n": 100000000000000000000}'),
                "json",
            ),
            ("tool call arguments with a lone surrogate", _tool_call_answer('{"text": "\\ud800"}'), "json"),
            (
                "message text with a lone surrogate",
                [{"role": "assistant", "content": '[{"type": "text", "text": "\\ud800"}]'}],
                "json",
            ),
        ]
    )
    def test_returns_render_ready_content_beside_the_event(
        self, _name: str, output: list[dict[str, object]], output_kind: str
    ) -> None:
        create_node_trace(self.team, extra_properties={"$ai_output_choices": output})

        response = self.client.get(self._url("trace-1", encode_segment(GENERATION)))

        assert response.status_code == 200, response.content
        content = response.json()["content"]
        assert (content["input"]["kind"], content["output"]["kind"]) == ("messages", output_kind)

    @parameterized.expand([("visible", False, True), ("restricted for the viewer", True, False)])
    def test_content_shows_the_input_unless_the_viewer_may_not_read_it(
        self, _name: str, restricted: bool, input_shown: bool
    ) -> None:
        if restricted:
            restrict_property(self, "$ai_input")
        create_node_trace(self.team)

        response = self.client.get(self._url("trace-1", encode_segment(GENERATION)))

        assert response.status_code == 200, response.content
        content = response.json()["content"]
        assert ("Why did my invoice go up?" in json.dumps(content["input"])) is input_shown
        assert content["output"]["kind"] == "messages"

    def test_a_team_recipe_applies_to_the_content(self) -> None:
        ParserRecipe.objects.unscoped().create(team=self.team, name="tickets", source=TICKET_RECIPE)
        create_node_trace(self.team, extra_properties={"$ai_input": TICKET})

        content = self.client.get(self._url("trace-1", encode_segment(GENERATION))).json()["content"]

        assert content["input"]["kind"] == "messages"
        assert "Ticket T-42: Refund requested" in json.dumps(content["input"])

    @parameterized.expand([("plain id", "trace-1"), ("id with a slash", "a/b")])
    def test_root_node_is_the_trace_event(self, _name: str, trace_id: str) -> None:
        create_node_trace(self.team, trace_id)

        body = self.client.get(self._url(trace_id, encode_segment(trace_id))).json()

        assert (body["id"], body["kind"]) == (trace_id, "trace")
        assert set(body["event"]) == {"name", "uuid", "timestamp"}
        assert body["content"] == {
            "input": {"kind": "json", "value": {"question": "Why?"}},
            "output": {"kind": "json", "value": None},
        }

    def test_root_without_a_trace_event_has_no_event(self) -> None:
        create_node_trace(self.team, with_trace_event=False)

        response = self.client.get(self._url("trace-1", encode_segment("trace-1")))

        assert response.status_code == 200
        assert response.json()["event"] is None
        assert response.json()["content"] == {
            "input": {"kind": "json", "value": None},
            "output": {"kind": "json", "value": None},
        }

    @parameterized.expand(
        [
            ("unknown node", "trace-1", "00000000-0000-0000-0000-00000000ffff"),
            ("root of an unknown trace", "trace-2", "trace-2"),
            ("node of another trace", "trace-2", GENERATION),
        ]
    )
    def test_node_not_found(self, _name: str, trace_id: str, node_id: str) -> None:
        create_node_trace(self.team)

        assert self.client.get(self._url(trace_id, encode_segment(node_id))).status_code == 404

    @parameterized.expand(
        [
            ("malformed trace segment", "A", encode_segment(GENERATION)),
            ("malformed node segment", encode_segment("trace-1"), "A"),
        ]
    )
    def test_rejects_a_malformed_segment(self, _name: str, trace_segment: str, node_segment: str) -> None:
        create_node_trace(self.team)

        url = f"/api/projects/{self.team.id}/ai_observability/traces/{trace_segment}/nodes/{node_segment}/"
        assert self.client.get(url).status_code == 400


class TestTraceNodeRawView(ClickhouseTestMixin, APIBaseTest):
    def _url(self, trace_segment: str, node_segment: str) -> str:
        return f"/api/projects/{self.team.id}/ai_observability/traces/{trace_segment}/nodes/{node_segment}/raw/"

    def test_returns_the_event_without_content(self) -> None:
        create_node_trace(self.team)

        response = self.client.get(self._url(encode_segment("trace-1"), encode_segment(GENERATION)))

        assert response.status_code == 200, response.content
        body = response.json()
        assert (body["id"], body["kind"]) == (GENERATION, "generation")
        assert "content" not in body
        assert body["event"]["ioKeys"] == {"input": "$ai_input", "output": "$ai_output_choices", "tools": "$ai_tools"}
        assert body["event"]["properties"]["$ai_input"] == QUESTION

    def test_root_without_a_trace_event_has_no_event(self) -> None:
        create_node_trace(self.team, with_trace_event=False)

        response = self.client.get(self._url(encode_segment("trace-1"), encode_segment("trace-1")))

        assert response.status_code == 200
        assert (response.json()["kind"], response.json()["event"]) == ("trace", None)

    def test_node_not_found(self) -> None:
        create_node_trace(self.team)

        response = self.client.get(
            self._url(encode_segment("trace-1"), encode_segment("00000000-0000-0000-0000-00000000ffff"))
        )

        assert response.status_code == 404

    def test_rejects_a_malformed_segment(self) -> None:
        create_node_trace(self.team)

        assert self.client.get(self._url(encode_segment("trace-1"), "A")).status_code == 400

    def test_masks_properties_the_viewer_may_not_read(self) -> None:
        restrict_property(self, "secret_plan")
        create_node_trace(self.team, extra_properties={"secret_plan": "enterprise"})

        properties = self.client.get(self._url(encode_segment("trace-1"), encode_segment(GENERATION))).json()["event"][
            "properties"
        ]

        assert "secret_plan" not in properties
        assert properties["$ai_provider"] == "openai"


class TestTraceNodeDatasetItemView(ClickhouseTestMixin, APIBaseTest):
    def _url(self, trace_segment: str, node_segment: str) -> str:
        return (
            f"/api/projects/{self.team.id}/ai_observability/traces/{trace_segment}/nodes/{node_segment}/dataset_item/"
        )

    def _read(self, node_id: str) -> dict:
        response = self.client.get(
            self._url(encode_segment("trace-1"), encode_segment(node_id)), {"timestamp_hint": "2026-09-01T10:00:00Z"}
        )
        assert response.status_code == 200, response.content
        return response.json()

    def test_returns_the_generation_as_a_dataset_item(self) -> None:
        create_node_trace(self.team, extra_properties={"plan": "pro"})

        assert self._read(GENERATION) == {
            "clientItemId": GENERATION,
            "sourceTraceId": "trace-1",
            "sourceEventId": GENERATION,
            "sourceTimestamp": "2026-09-01T10:00:00Z",
            "input": QUESTION,
            "sourceOutput": ANSWER,
            "metadata": {"plan": "pro"},
        }

    def test_root_with_a_trace_event_saves_its_state_without_metadata(self) -> None:
        create_node_trace(self.team, extra_properties={"plan": "pro"})

        item = self._read("trace-1")

        assert item["clientItemId"] == "trace-1"
        assert item["input"] == {"question": "Why?"}
        assert item["sourceOutput"] is None
        assert item["metadata"] == {}

    def test_root_without_a_trace_event_saves_empty_content(self) -> None:
        create_node_trace(self.team, with_trace_event=False)

        item = self._read("trace-1")

        assert (item["input"], item["sourceOutput"], item["metadata"]) == ({}, None, {})

    def test_matches_what_the_raw_read_gives(self) -> None:
        create_node_trace(self.team, extra_properties={"plan": "pro"})
        raw = self.client.get(
            f"/api/projects/{self.team.id}/ai_observability/traces/{encode_segment('trace-1')}/nodes/{encode_segment(GENERATION)}/raw/"
        ).json()["event"]

        item = self._read(GENERATION)

        properties = raw["properties"]
        assert item["input"] == properties[raw["ioKeys"]["input"]]
        assert item["sourceOutput"] == properties[raw["ioKeys"]["output"]]
        assert item["metadata"] == {key: value for key, value in properties.items() if not key.startswith("$")}

    def test_hides_properties_the_viewer_may_not_read(self) -> None:
        restrict_property(self, "secret_plan")
        create_node_trace(self.team, extra_properties={"secret_plan": "enterprise", "plan": "pro"})

        assert self._read(GENERATION)["metadata"] == {"plan": "pro"}

    def test_requires_the_timestamp_hint(self) -> None:
        create_node_trace(self.team)

        response = self.client.get(self._url(encode_segment("trace-1"), encode_segment(GENERATION)))

        assert response.status_code == 400

    def test_node_not_found(self) -> None:
        create_node_trace(self.team)

        response = self.client.get(
            self._url(encode_segment("trace-1"), encode_segment("00000000-0000-0000-0000-00000000ffff")),
            {"timestamp_hint": "2026-09-01T10:00:00Z"},
        )

        assert response.status_code == 404

    def test_rejects_a_malformed_segment(self) -> None:
        create_node_trace(self.team)

        response = self.client.get(
            self._url(encode_segment("trace-1"), "A"), {"timestamp_hint": "2026-09-01T10:00:00Z"}
        )

        assert response.status_code == 400


class TestTraceNodeParserTestView(ClickhouseTestMixin, APIBaseTest):
    def _url(self, node_id: str = GENERATION) -> str:
        return (
            f"/api/projects/{self.team.id}/ai_observability/traces/{encode_segment('trace-1')}"
            f"/nodes/{encode_segment(node_id)}/parser_test/"
        )

    def test_a_parser_that_parses_the_unrecognized_input_passes_and_is_not_saved(self) -> None:
        create_node_trace(self.team, extra_properties={"$ai_input": TICKET})

        response = self.client.post(self._url(), {"source": TICKET_RECIPE}, format="json")

        assert response.status_code == 200, response.content
        body = response.json()
        assert body["passed"] is True
        assert body["input"] == {"neededFixing": True, "fixed": True, "broken": False, "error": None}
        assert body["output"] == {"neededFixing": False, "fixed": False, "broken": False, "error": None}
        assert [part["text"] for part in body["content"]["input"]["messages"][0]["parts"]] == [
            "Ticket T-42: Refund requested"
        ]
        assert not ParserRecipe.objects.for_team(self.team.pk).exists()

    def test_a_side_a_saved_parser_already_recognizes_needs_no_fixing(self) -> None:
        create_node_trace(self.team, extra_properties={"$ai_input": TICKET})
        ParserRecipe.objects.unscoped().create(team=self.team, name="tickets", source=TICKET_RECIPE)

        response = self.client.post(self._url(), {"source": TICKET_RECIPE.replace("Ticket", "Case")}, format="json")

        assert response.status_code == 200, response.content
        assert (response.json()["passed"], response.json()["input"]["neededFixing"]) == (False, False)

    def test_a_parser_that_does_not_compile_is_a_400_with_the_reason(self) -> None:
        create_node_trace(self.team)

        response = self.client.post(self._url(), {"source": "foo: bar"}, format="json")

        assert response.status_code == 400, response.content
        assert "rules" in response.json()["detail"]

    def test_node_not_found(self) -> None:
        create_node_trace(self.team)

        response = self.client.post(
            self._url("00000000-0000-0000-0000-00000000dead"), {"source": TICKET_RECIPE}, format="json"
        )

        assert response.status_code == 404, response.content
        assert response.json()["detail"] == "Node not found."

    def test_an_api_key_that_can_only_read_can_test_a_parser(self) -> None:
        create_node_trace(self.team, extra_properties={"$ai_input": TICKET})
        key = self.create_personal_api_key_with_scopes(["llm_analytics:read"])
        self.client.logout()

        response = self.client.post(
            self._url(), {"source": TICKET_RECIPE}, format="json", headers={"authorization": f"Bearer {key}"}
        )

        assert response.status_code == 200, response.content
