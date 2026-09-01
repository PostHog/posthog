from typing import Any

from parameterized import parameterized

from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.knock.template_knock import template as template_knock
from posthog.cdp.validation import generate_template_bytecode

from common.hogvm.python.execute import execute_bytecode
from common.hogvm.python.utils import HogVMException

USER_ID_DEFAULT = next(item for item in template_knock.inputs_schema if item["key"] == "userId")["default"]

DEVICE_ID = "0192c3d4-5e6f-7081-9234-56789abcdef0"
PERSON = {"id": "1c1e0d6f-2b3a-4c5d-8e9f-0a1b2c3d4e5f", "properties": {}}


def resolve_user_id_default(globals: dict) -> Any:
    bytecode = generate_template_bytecode(USER_ID_DEFAULT, set())
    try:
        return execute_bytecode(bytecode, globals).result
    except HogVMException:
        # Warehouse rows and account batches build globals with no person key at all, which the VM
        # rejects. That leaves the destination without a user ID, same as an unset value.
        return None


def create_inputs(**kwargs):
    inputs = {
        "webhookUrl": "https://api.knock.app/integrations/receive/tkN_P18rTjBq30waf1RLp",
        "include_all_properties": False,
        "userId": "8b9c729c-c59b-4c39-b5a6-af9fa1233054",
        "attributes": {"phone": "0123456789"},
    }
    inputs.update(kwargs)

    return inputs


class TestTemplateKnock(BaseHogFunctionTemplateTest):
    template = template_knock

    def test_function_works(self):
        self.run_function(
            inputs=create_inputs(),
            globals={
                "event": {
                    "uuid": "9d67cc3f-edf7-490d-b311-f03c21c64caf",
                    "distinct_id": "8b9c729c-c59b-4c39-b5a6-af9fa1233054",
                    "event": "$pageview",
                    "timestamp": "2024-09-16T16:11:48.577Z",
                    "url": "http://localhost:8000/project/1/events/",
                    "properties": {
                        "$current_url": "http://localhost:8000/project/1/pipeline/destinations/hog-0191fb90-bb37-0000-fba4-3377db3ac5e6/configuration",
                        "$browser": "Chrome",
                        "price": 15,
                        "phone": "0123456789",
                    },
                },
            },
        )

        assert self.get_mock_fetch_calls()[0] == (
            "https://api.knock.app/integrations/receive/tkN_P18rTjBq30waf1RLp",
            {
                "method": "POST",
                "headers": {
                    "Content-Type": "application/json",
                },
                "body": {
                    "type": "track",
                    "event": "$pageview",
                    "userId": "8b9c729c-c59b-4c39-b5a6-af9fa1233054",
                    "properties": {"phone": "0123456789"},
                    "messageId": "9d67cc3f-edf7-490d-b311-f03c21c64caf",
                    "timestamp": "2024-09-16T16:11:48.577Z",
                },
            },
        )

    def test_body_includes_all_properties_if_set(self):
        self.run_function(
            inputs=create_inputs(include_all_properties=False),
            globals={
                "event": {
                    "uuid": "9d67cc3f-edf7-490d-b311-f03c21c64caf",
                    "distinct_id": "8b9c729c-c59b-4c39-b5a6-af9fa1233054",
                    "event": "$pageview",
                    "timestamp": "2024-09-16T16:11:48.577Z",
                    "url": "http://localhost:8000/project/1/events/",
                    "properties": {
                        "$current_url": "http://localhost:8000/project/1/pipeline/destinations/hog-0191fb90-bb37-0000-fba4-3377db3ac5e6/configuration",
                        "$browser": "Chrome",
                        "price": 15,
                    },
                },
            },
        )

        assert self.get_mock_fetch_calls()[0][1]["body"]["properties"] == {"phone": "0123456789"}

        self.run_function(
            inputs=create_inputs(include_all_properties=True),
            globals={
                "event": {
                    "uuid": "9d67cc3f-edf7-490d-b311-f03c21c64caf",
                    "distinct_id": "8b9c729c-c59b-4c39-b5a6-af9fa1233054",
                    "event": "$pageview",
                    "timestamp": "2024-09-16T16:11:48.577Z",
                    "url": "http://localhost:8000/project/1/events/",
                    "properties": {
                        "$current_url": "http://localhost:8000/project/1/pipeline/destinations/hog-0191fb90-bb37-0000-fba4-3377db3ac5e6/configuration",
                        "$browser": "Chrome",
                        "price": 15,
                    },
                },
            },
        )

        assert self.get_mock_fetch_calls()[0][1]["body"]["properties"] == {
            "price": 15,
            "$current_url": "http://localhost:8000/project/1/pipeline/destinations/hog-0191fb90-bb37-0000-fba4-3377db3ac5e6/configuration",
            "$browser": "Chrome",
            "phone": "0123456789",
        }

    def test_function_requires_identifier(self):
        self.run_function(inputs=create_inputs(userId=""))

        assert not self.get_mock_fetch_calls()
        assert self.get_mock_print_calls() == [("No User ID set. Skipping...",)]

    @parameterized.expand(
        [
            (
                "server-side event carrying no device ID",
                {"event": {"distinct_id": "app-user-42", "properties": {}}, "person": PERSON},
                "app-user-42",
            ),
            (
                "identified browser event",
                {
                    "event": {"distinct_id": "app-user-42", "properties": {"$device_id": DEVICE_ID}},
                    "person": PERSON,
                },
                "app-user-42",
            ),
            (
                "anonymous browser event",
                {
                    "event": {"distinct_id": DEVICE_ID, "properties": {"$device_id": DEVICE_ID}},
                    "person": PERSON,
                },
                None,
            ),
            (
                "event with an empty person",
                {"event": {"distinct_id": "app-user-42", "properties": {}}, "person": None},
                None,
            ),
            (
                "warehouse row built without a person",
                {"event": {"distinct_id": "data-warehouse-table-distinct-id-do-not-use", "properties": {}}},
                None,
            ),
        ]
    )
    def test_user_id_default_only_resolves_for_identified_people(self, _name, globals, expected):
        assert resolve_user_id_default(globals) == expected
