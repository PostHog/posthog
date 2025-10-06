from inline_snapshot import snapshot

from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.loops.template_loops import (
    template as template_loops,
    template_send_event as template_loops_send_event,
)


class TestTemplateLoops(BaseHogFunctionTemplateTest):
    template = template_loops

    def _inputs(self, **kwargs):
        inputs = {
            "apiKey": "1cac089e00a708680bdb1ed9f082d5bf",
            "email": "max@posthog.com",
            "include_all_properties": False,
            "properties": {"firstName": "Max", "lastName": "AI"},
        }
        inputs.update(kwargs)
        return inputs

    def test_function_works(self):
        self.run_function(
            inputs=self._inputs(),
            globals={
                "person": {
                    "id": "c44562aa-c649-426a-a9d4-093fef0c2a4a",
                    "properties": {"name": "Max", "company": "PostHog"},
                },
            },
        )

        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://app.loops.so/api/v1/contacts/update",
                {
                    "method": "POST",
                    "headers": {
                        "Content-Type": "application/json",
                        "Authorization": "Bearer 1cac089e00a708680bdb1ed9f082d5bf",
                    },
                    "body": {
                        "email": "max@posthog.com",
                        "userId": "c44562aa-c649-426a-a9d4-093fef0c2a4a",
                        "firstName": "Max",
                        "lastName": "AI",
                    },
                },
            )
        )

    def test_include_all_properties(self):
        self.run_function(
            inputs=self._inputs(include_all_properties=True),
            globals={
                "person": {
                    "id": "c44562aa-c649-426a-a9d4-093fef0c2a4a",
                    "properties": {"company": "PostHog"},
                },
            },
        )

        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://app.loops.so/api/v1/contacts/update",
                {
                    "method": "POST",
                    "headers": {
                        "Content-Type": "application/json",
                        "Authorization": "Bearer 1cac089e00a708680bdb1ed9f082d5bf",
                    },
                    "body": {
                        "email": "max@posthog.com",
                        "userId": "c44562aa-c649-426a-a9d4-093fef0c2a4a",
                        "company": "PostHog",
                        "firstName": "Max",
                        "lastName": "AI",
                    },
                },
            )
        )

    def test_function_requires_identifier(self):
        self.run_function(
            inputs=self._inputs(email=""),
        )

        assert not self.get_mock_fetch_calls()
        assert self.get_mock_print_calls() == snapshot([("No email set. Skipping...",)])


class TestTemplateLoopsEvent(BaseHogFunctionTemplateTest):
    template = template_loops_send_event

    def _inputs(self, **kwargs):
        inputs = {
            "apiKey": "1cac089e00a708680bdb1ed9f082d5bf",
            "email": "max@posthog.com",
            "include_all_properties": False,
            "properties": {"product": "PostHog"},
        }
        inputs.update(kwargs)
        return inputs

    def test_function_works(self):
        self.run_function(
            inputs=self._inputs(),
            globals={
                "person": {
                    "id": "c44562aa-c649-426a-a9d4-093fef0c2a4a",
                    "properties": {"name": "Max", "company": "PostHog"},
                },
                "event": {
                    "event": "pageview",
                    "properties": {"pathname": "/pricing"},
                },
            },
        )

        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://app.loops.so/api/v1/events/send",
                {
                    "method": "POST",
                    "headers": {
                        "Content-Type": "application/json",
                        "Authorization": "Bearer 1cac089e00a708680bdb1ed9f082d5bf",
                    },
                    "body": {
                        "email": "max@posthog.com",
                        "userId": "c44562aa-c649-426a-a9d4-093fef0c2a4a",
                        "eventName": "pageview",
                        "eventProperties": {
                            "product": "PostHog",
                        },
                    },
                },
            )
        )

    def test_include_all_properties(self):
        self.run_function(
            inputs=self._inputs(include_all_properties=True),
            globals={
                "person": {
                    "id": "c44562aa-c649-426a-a9d4-093fef0c2a4a",
                    "properties": {"company": "PostHog"},
                },
                "event": {
                    "event": "pageview",
                    "properties": {"pathname": "/pricing"},
                },
            },
        )

        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://app.loops.so/api/v1/events/send",
                {
                    "method": "POST",
                    "headers": {
                        "Content-Type": "application/json",
                        "Authorization": "Bearer 1cac089e00a708680bdb1ed9f082d5bf",
                    },
                    "body": {
                        "email": "max@posthog.com",
                        "userId": "c44562aa-c649-426a-a9d4-093fef0c2a4a",
                        "eventName": "pageview",
                        "eventProperties": {
                            "product": "PostHog",
                            "pathname": "/pricing",
                        },
                    },
                },
            )
        )

    def test_function_requires_identifier(self):
        self.run_function(
            inputs=self._inputs(email=""),
        )

        assert not self.get_mock_fetch_calls()
        assert self.get_mock_print_calls() == snapshot([("No email set. Skipping...",)])
