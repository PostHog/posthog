from inline_snapshot import snapshot
from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.attio.template_attio import (
    template_contact as template_attio_contact,
    template_user as template_attio_user,
    template_workspace as template_attio_workspace,
)


def create_contact_inputs(**kwargs):
    inputs = {
        "apiKey": "apikey12345",
        "email": "max@posthog.com",
        "personAttributes": {"name": "Max", "job_title": "Mascot"},
    }
    inputs.update(kwargs)
    return inputs


def create_user_inputs(**kwargs):
    inputs = {
        "apiKey": "apikey12345",
        "email": "max@posthog.com",
        "userId": "userid12345",
        "personAttributes": {},
        "userAttributes": {},
    }
    inputs.update(kwargs)
    return inputs


def create_workspace_inputs(**kwargs):
    inputs = {
        "apiKey": "apikey12345",
        "workspaceId": "workspaceid12345",
        "companyDomain": "posthog.com",
        "companyAttributes": {"name": "PostHog"},
        "workspaceAttributes": {},
    }
    inputs.update(kwargs)
    return inputs


class TestTemplateAttioContact(BaseHogFunctionTemplateTest):
    template = template_attio_contact

    def test_contact_function_works(self):
        self.mock_fetch_response = lambda *args: {"status": 200, "body": {"ok": True}}  # type: ignore
        self.run_function(inputs=create_contact_inputs())
        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://api.attio.com/v2/objects/people/records?matching_attribute=email_addresses",
                {
                    "body": {
                        "data": {
                            "values": {
                                "email_addresses": [{"email_address": "max@posthog.com"}],
                                "name": "Max",
                                "job_title": "Mascot",
                            }
                        }
                    },
                    "method": "PUT",
                    "headers": {
                        "Authorization": "Bearer apikey12345",
                        "Content-Type": "application/json",
                    },
                },
            )
        )

    def test_contact_ignores_empty_values(self):
        self.mock_fetch_response = lambda *args: {"status": 200, "body": {"ok": True}}  # type: ignore
        self.run_function(inputs=create_contact_inputs(personAttributes={"name": "Max", "job_title": ""}))
        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://api.attio.com/v2/objects/people/records?matching_attribute=email_addresses",
                {
                    "body": {
                        "data": {
                            "values": {
                                "email_addresses": [{"email_address": "max@posthog.com"}],
                                "name": "Max",
                            }
                        }
                    },
                    "method": "PUT",
                    "headers": {
                        "Authorization": "Bearer apikey12345",
                        "Content-Type": "application/json",
                    },
                },
            )
        )


class TestTemplateAttioUser(BaseHogFunctionTemplateTest):
    template = template_attio_user

    def test_user_function_works(self):
        self.mock_fetch_response = lambda *args: {"status": 200, "body": {"ok": True}}  # type: ignore
        self.run_function(inputs=create_user_inputs())

        # First call should be to create/update Person
        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://api.attio.com/v2/objects/people/records?matching_attribute=email_addresses",
                {
                    "method": "PUT",
                    "headers": {"Authorization": "Bearer apikey12345", "Content-Type": "application/json"},
                    "body": {"data": {"values": {"email_addresses": [{"email_address": "max@posthog.com"}]}}},
                },
            )
        )

        # Second call should be to create/update User
        assert self.get_mock_fetch_calls()[1] == snapshot(
            (
                "https://api.attio.com/v2/objects/users/records?matching_attribute=user_id",
                {
                    "method": "PUT",
                    "headers": {"Authorization": "Bearer apikey12345", "Content-Type": "application/json"},
                    "body": {
                        "data": {
                            "values": {
                                "user_id": "userid12345",
                                "primary_email_address": [{"email_address": "max@posthog.com"}],
                                "person": "max@posthog.com",
                            }
                        }
                    },
                },
            )
        )


class TestTemplateAttioWorkspace(BaseHogFunctionTemplateTest):
    template = template_attio_workspace

    def test_workspace_user_linking_logic(self):
        self.mock_fetch_response = lambda *args: {"status": 200, "body": {"ok": True}}  # type: ignore

        # Test WITH userId
        inputs_with_user = create_workspace_inputs(userId="user123")
        self.run_function(inputs=inputs_with_user)
        workspace_call = self.get_mock_fetch_calls()[1]
        assert workspace_call[1]["body"]["data"]["values"]["users"] == ["user123"]

        # Test WITHOUT userId (or empty)
        inputs_no_user = create_workspace_inputs(userId="")
        self.run_function(inputs=inputs_no_user)
        workspace_call = self.get_mock_fetch_calls()[1]
        assert "users" not in workspace_call[1]["body"]["data"]["values"]

    def test_workspace_function_works(self):
        self.mock_fetch_response = lambda *args: {"status": 200, "body": {"ok": True}}  # type: ignore
        self.run_function(inputs=create_workspace_inputs())

        # First call should be to create/update Company
        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://api.attio.com/v2/objects/companies/records?matching_attribute=domains",
                {
                    "method": "PUT",
                    "headers": {"Authorization": "Bearer apikey12345", "Content-Type": "application/json"},
                    "body": {"data": {"values": {"domains": [{"domain": "posthog.com"}], "name": "PostHog"}}},
                },
            )
        )

        # Second call should be to create/update Workspace
        assert self.get_mock_fetch_calls()[1] == snapshot(
            (
                "https://api.attio.com/v2/objects/workspaces/records?matching_attribute=workspace_id",
                {
                    "method": "PUT",
                    "headers": {"Authorization": "Bearer apikey12345", "Content-Type": "application/json"},
                    "body": {"data": {"values": {"workspace_id": "workspaceid12345", "company": "posthog.com"}}},
                },
            )
        )
