import json
from types import SimpleNamespace

from unittest import TestCase

from ee.hogai.core.workflow_payload import get_workflow_input_size_estimates


class TestWorkflowPayload(TestCase):
    def test_size_estimates_expose_only_allowlisted_field_sizes(self) -> None:
        message = {"content": "A question with a unicode character: é"}
        inputs = SimpleNamespace(
            message=message,
            contextual_tools={"execute_sql": {"query": "SELECT 1"}},
            billing_context=None,
            resume_payload={"approved": True},
            secret="not logged",
        )

        self.assertEqual(
            get_workflow_input_size_estimates(inputs),
            {
                "message": len(json.dumps(message, ensure_ascii=False).encode("utf-8")),
                "contextual_tools": 38,
                "resume_payload": 18,
            },
        )

    def test_invalid_field_does_not_hide_other_sizes(self) -> None:
        circular: list[object] = []
        circular.append(circular)
        inputs = SimpleNamespace(message=circular, contextual_tools={})

        self.assertEqual(get_workflow_input_size_estimates(inputs), {"contextual_tools": 2})
