import json

from posthog.test.base import APIBaseTest

from posthog.models import PersonalAPIKey
from posthog.models.personal_api_key import hash_key_value
from posthog.models.utils import generate_random_token_personal

MCP_PROTOCOL_VERSION = "2025-06-18"


class MCPTestMixin:
    def _create_mcp_payload(self, method: str, params: dict, request_id: int = 1) -> dict:
        return {"jsonrpc": "2.0", "method": method, "params": params, "id": request_id}

    def _make_mcp_request(self, payload: dict, authenticated: bool = True):
        headers = {
            "HTTP_MCP_PROTOCOL_VERSION": MCP_PROTOCOL_VERSION,
            "HTTP_ACCEPT": "application/json, text/event-stream",
        }

        if authenticated:
            headers["HTTP_AUTHORIZATION"] = f"Bearer {self.api_key_value}"

        return self.client.post("/mcp", data=json.dumps(payload), content_type="application/json", **headers)

    def _assert_mcp_response(self, response, expected_id: int, expected_status: int = 200):
        self.assertEqual(response.status_code, expected_status)

        if expected_status == 200:
            data = response.json()
            self.assertEqual(data["jsonrpc"], "2.0")
            self.assertEqual(data["id"], expected_id)
            return data
        return None

    def _get_initialize_params(self) -> dict:
        return {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "clientInfo": {"name": "test-client", "version": "1.0.0"},
        }


class TestMCPAuthentication(APIBaseTest, MCPTestMixin):
    def setUp(self):
        super().setUp()
        self.api_key_value = generate_random_token_personal()
        self.personal_api_key = PersonalAPIKey.objects.create(
            label="Test MCP Key", user=self.user, secure_value=hash_key_value(self.api_key_value)
        )

    def test_mcp_requires_authentication(self):
        payload = self._create_mcp_payload("initialize", self._get_initialize_params())
        response = self._make_mcp_request(payload, authenticated=False)
        self._assert_mcp_response(response, 1, expected_status=401)

    def test_mcp_with_valid_authentication(self):
        payload = self._create_mcp_payload("initialize", self._get_initialize_params())
        response = self._make_mcp_request(payload)
        data = self._assert_mcp_response(response, 1)

        self.assertIn("result", data)
        self.assertEqual(data["result"]["serverInfo"]["name"], "PostHog MCP")


class TestMCPIntegration(APIBaseTest, MCPTestMixin):
    def setUp(self):
        super().setUp()
        self.api_key_value = generate_random_token_personal()
        self.personal_api_key = PersonalAPIKey.objects.create(
            label="Test MCP Integration Key", user=self.user, secure_value=hash_key_value(self.api_key_value)
        )

    def test_mcp_server_initialization(self):
        payload = self._create_mcp_payload("initialize", self._get_initialize_params())
        response = self._make_mcp_request(payload)
        data = self._assert_mcp_response(response, 1)

        self.assertIn("result", data)
        self.assertEqual(data["result"]["serverInfo"]["name"], "PostHog MCP")

    def test_list_available_tools(self):
        payload = self._create_mcp_payload("tools/list", {}, 2)
        response = self._make_mcp_request(payload)
        data = self._assert_mcp_response(response, 2)

        self.assertIn("result", data)
        tools = data["result"]["tools"]
        self.assertIsInstance(tools, list)

        add_tool = next((tool for tool in tools if tool["name"] == "add"), None)
        self.assertIsNotNone(add_tool, "Add tool should be available")
        self.assertEqual(add_tool["description"], "Add two integers together.")

        self.assertIn("inputSchema", add_tool)
        self.assertIn("properties", add_tool["inputSchema"])
        self.assertIn("a", add_tool["inputSchema"]["properties"])
        self.assertIn("b", add_tool["inputSchema"]["properties"])

    def test_call_add_tool(self):
        test_cases = [
            ({"a": 5, "b": 3}, "8"),
            ({"a": 0, "b": 0}, "0"),
            ({"a": -5, "b": 10}, "5"),
            ({"a": 1000, "b": 2000}, "3000"),
        ]

        for args, expected in test_cases:
            with self.subTest(args=args, expected=expected):
                payload = self._create_mcp_payload("tools/call", {"name": "add", "arguments": args}, 3)

                response = self._make_mcp_request(payload)
                data = self._assert_mcp_response(response, 3)

                self.assertIn("result", data)
                result = data["result"]
                self.assertIn("content", result)
                self.assertEqual(len(result["content"]), 1)
                self.assertEqual(result["content"][0]["text"], expected)

    def test_call_tool_with_missing_arguments(self):
        payload = self._create_mcp_payload(
            "tools/call",
            {
                "name": "add",
                "arguments": {"a": 5},  # Missing 'b' argument
            },
            4,
        )

        response = self._make_mcp_request(payload)
        data = self._assert_mcp_response(response, 4)

        # MCP server returns errors in result with isError flag
        self.assertIn("result", data)
        result = data["result"]
        self.assertTrue(result.get("isError", False))
        content_text = result["content"][0]["text"].lower()
        self.assertTrue(
            "required" in content_text or "missing" in content_text,
            f"Expected 'required' or 'missing' in error, got: {result}",
        )

    def test_call_nonexistent_tool(self):
        payload = self._create_mcp_payload("tools/call", {"name": "nonexistent_tool", "arguments": {}}, 5)

        response = self._make_mcp_request(payload)
        data = self._assert_mcp_response(response, 5)

        # MCP server returns errors in result with isError flag
        self.assertIn("result", data)
        result = data["result"]
        self.assertTrue(result.get("isError", False))
        content_text = result["content"][0]["text"].lower()
        self.assertTrue(
            "not found" in content_text or "unknown" in content_text or "tool" in content_text,
            f"Expected 'not found', 'unknown', or 'tool' in error, got: {result}",
        )
