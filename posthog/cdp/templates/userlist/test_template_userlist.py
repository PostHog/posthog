from inline_snapshot import snapshot

from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.userlist.template_userlist import template as template_userlist


def create_inputs(**kwargs):
    inputs = {
        "push_key": "test_push_key",
        "user_identifier": "user_123",
        "user_email": "user@example.com",
        "user_properties": {"first_name": "John", "last_name": "Doe"},
        "company_identifier": None,
        "company_name": None,
        "company_properties": {"industry": None},
    }
    inputs.update(kwargs)
    return inputs


class TestTemplateUserlist(BaseHogFunctionTemplateTest):
    template = template_userlist

    def test_identify_event(self):
        self.run_function(
            inputs=create_inputs(),
            globals={
                "event": {"event": "$identify"},
                "person": {
                    "id": "user_123",
                    "properties": {"email": "user@example.com"},
                },
            },
        )

        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://incoming.userlist.com/posthog/users",
                {
                    "method": "POST",
                    "headers": {
                        "Authorization": "Push test_push_key",
                        "Accept": "application/json",
                        "Content-Type": "application/json; charset=utf-8",
                    },
                    "body": {
                        "email": "user@example.com",
                        "identifier": "user_123",
                        "properties": {"first_name": "John", "last_name": "Doe"},
                    },
                },
            )
        )

    def test_set_event(self):
        self.run_function(
            inputs=create_inputs(
                user_identifier="user_456",
                user_email="updated@example.com",
                user_properties={"first_name": "Jane", "last_name": "Smith"},
            ),
            globals={
                "event": {"event": "$set"},
                "person": {
                    "id": "user_456",
                    "properties": {"email": "updated@example.com"},
                },
            },
        )

        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://incoming.userlist.com/posthog/users",
                {
                    "method": "POST",
                    "headers": {
                        "Authorization": "Push test_push_key",
                        "Accept": "application/json",
                        "Content-Type": "application/json; charset=utf-8",
                    },
                    "body": {
                        "email": "updated@example.com",
                        "identifier": "user_456",
                        "properties": {"first_name": "Jane", "last_name": "Smith"},
                    },
                },
            )
        )

    def test_groupidentify_event(self):
        self.run_function(
            inputs=create_inputs(
                company_identifier="company_123",
                company_name="Acme Corp",
                company_properties={"industry": "Technology", "employee_count": "50"},
            ),
            globals={
                "event": {"event": "$groupidentify"},
                "person": {
                    "id": "user_123",
                    "properties": {"email": "user@example.com"},
                },
            },
        )

        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://incoming.userlist.com/posthog/companies",
                {
                    "method": "POST",
                    "headers": {
                        "Authorization": "Push test_push_key",
                        "Accept": "application/json",
                        "Content-Type": "application/json; charset=utf-8",
                    },
                    "body": {
                        "identifier": "company_123",
                        "name": "Acme Corp",
                        "properties": {"industry": "Technology", "employee_count": "50"},
                        "user": {
                            "identifier": "user_123",
                            "email": "user@example.com",
                            "properties": {"first_name": "John", "last_name": "Doe"},
                        },
                    },
                },
            )
        )

    def test_custom_event(self):
        self.run_function(
            inputs=create_inputs(
                company_identifier="company_123",
                company_name="Acme Corp",
                company_properties={"industry": "Technology"},
            ),
            globals={
                "event": {
                    "event": "button_clicked",
                    "timestamp": "2024-01-01T00:00:00Z",
                    "properties": {"button_name": "signup", "page": "homepage"},
                },
                "person": {
                    "id": "user_123",
                    "properties": {"email": "user@example.com"},
                },
            },
        )

        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://incoming.userlist.com/posthog/events",
                {
                    "method": "POST",
                    "headers": {
                        "Authorization": "Push test_push_key",
                        "Accept": "application/json",
                        "Content-Type": "application/json; charset=utf-8",
                    },
                    "body": {
                        "name": "button_clicked",
                        "user": {
                            "identifier": "user_123",
                            "email": "user@example.com",
                            "properties": {"first_name": "John", "last_name": "Doe"},
                        },
                        "company": {
                            "identifier": "company_123",
                            "name": "Acme Corp",
                            "properties": {"industry": "Technology"},
                        },
                        "occurred_at": "2024-01-01T00:00:00Z",
                        "properties": {"button_name": "signup", "page": "homepage"},
                    },
                },
            )
        )

    def test_compact_removes_null_values(self):
        self.run_function(
            inputs=create_inputs(
                user_email=None,
                user_properties={"first_name": "John", "last_name": None, "middle_name": None},
            ),
            globals={
                "event": {"event": "$identify"},
                "person": {
                    "id": "user_123",
                    "properties": {},
                },
            },
        )

        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://incoming.userlist.com/posthog/users",
                {
                    "method": "POST",
                    "headers": {
                        "Authorization": "Push test_push_key",
                        "Accept": "application/json",
                        "Content-Type": "application/json; charset=utf-8",
                    },
                    "body": {
                        "identifier": "user_123",
                        "properties": {"first_name": "John"},
                    },
                },
            )
        )

    def test_user_payload_without_email_and_identifier_is_not_sent(self):
        self.run_function(
            inputs=create_inputs(
                user_identifier=None,
                user_email=None,
                user_properties={"first_name": "John"},
            ),
            globals={
                "event": {"event": "$identify"},
                "person": {
                    "id": None,
                    "properties": {},
                },
            },
        )

        assert self.get_mock_fetch_calls() == []
        assert self.get_mock_print_calls() == snapshot([("Error sending data to Userlist: Invalid payload",)])

    def test_company_payload_without_identifier_is_not_sent(self):
        self.run_function(
            inputs=create_inputs(
                user_properties={"first_name": "John"},
                company_name="Acme Corp",
                company_properties={"industry": "Technology"},
            ),
            globals={
                "event": {"event": "$groupidentify"},
                "person": {
                    "id": "user_123",
                    "properties": {"email": "user@example.com"},
                },
            },
        )

        assert self.get_mock_fetch_calls() == []
        assert self.get_mock_print_calls() == snapshot([("Error sending data to Userlist: Invalid payload",)])

    def test_event_payload_without_user_and_company_is_not_sent(self):
        self.run_function(
            inputs=create_inputs(
                user_identifier=None,
                user_email=None,
                user_properties={"first_name": "John"},
                company_properties={"industry": "Technology"},
            ),
            globals={
                "event": {"event": "custom_event", "timestamp": "2024-01-01T00:00:00Z", "properties": {}},
                "person": {
                    "id": None,
                    "properties": {},
                },
            },
        )

        assert self.get_mock_fetch_calls() == []
        assert self.get_mock_print_calls() == snapshot([("Error sending data to Userlist: Invalid payload",)])

    def test_function_prints_error_on_bad_status(self):
        self.mock_fetch_response = lambda *args: {"status": 400, "body": {"error": "Invalid request"}}  # type: ignore
        self.run_function(
            inputs=create_inputs(),
            globals={
                "event": {"event": "$identify"},
                "person": {
                    "id": "user_123",
                    "properties": {"email": "user@example.com"},
                },
            },
        )

        assert self.get_mock_print_calls() == snapshot(
            [("Error sending data to Userlist: 400 - {'error': 'Invalid request'}",)]
        )

    def test_system_events_are_skipped(self):
        self.run_function(
            inputs=create_inputs(),
            globals={
                "event": {
                    "event": "$pageview",
                    "timestamp": "2024-01-01T00:00:00Z",
                    "properties": {"url": "https://example.com"},
                },
                "person": {
                    "id": "user_123",
                    "properties": {"email": "user@example.com"},
                },
            },
        )

        assert self.get_mock_fetch_calls() == []
        assert self.get_mock_print_calls() == snapshot([("Skipping event $pageview as it is not supported.",)])
