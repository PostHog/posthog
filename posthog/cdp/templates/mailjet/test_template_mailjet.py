from inline_snapshot import snapshot

from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.mailjet.template_mailjet import template_create_contact, template_update_contact_list


def create_inputs(**kwargs):
    inputs = {"api_key": "API_KEY", "secret_key": "SECRET_KEY", "email": "example@posthog.com"}
    inputs.update(kwargs)
    return inputs


class TestTemplateMailjetCreateContact(BaseHogFunctionTemplateTest):
    template = template_create_contact

    def test_function_works(self):
        self.run_function(inputs=create_inputs(name="Example", is_excluded_from_campaigns=False))

        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://api.mailjet.com/v3/REST/contact/",
                {
                    "method": "POST",
                    "headers": {"Authorization": "Basic QVBJX0tFWTpTRUNSRVRfS0VZ", "Content-Type": "application/json"},
                    "body": {"Email": "example@posthog.com", "Name": "Example", "IsExcludedFromCampaigns": False},
                },
            )
        )

    def test_function_ignores_no_email(self):
        self.run_function(inputs=create_inputs(email=""))

        assert self.get_mock_fetch_calls() == []


class TestTemplateMailjetUpdateContactList(BaseHogFunctionTemplateTest):
    template = template_update_contact_list

    def test_function_works(self):
        self.run_function(inputs=create_inputs(contact_list_id=123, action="addnoforce"))

        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://api.mailjet.com/v3/REST/contact/example@posthog.com/managecontactlists",
                {
                    "method": "POST",
                    "headers": {"Authorization": "Basic QVBJX0tFWTpTRUNSRVRfS0VZ", "Content-Type": "application/json"},
                    "body": {"ContactsLists": [{"Action": "addnoforce", "ListID": 123}]},
                },
            )
        )

    def test_function_ignores_no_email(self):
        self.run_function(inputs=create_inputs(email=""))

        assert self.get_mock_fetch_calls() == []
