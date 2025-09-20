from inline_snapshot import snapshot

from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.june.template_june import template as template_june


def create_inputs(**kwargs):
    inputs = {
        "apiKey": "abcdef123456",
        "include_all_properties": False,
        "properties": {"name": "Max AI", "email": "max@posthog.com"},
    }
    inputs.update(kwargs)

    return inputs


class TestTemplateJune(BaseHogFunctionTemplateTest):
    template = template_june

    def test_function_works(self):
        self.run_function(
            inputs=create_inputs(),
            globals={
                "event": {
                    "event": "$pageview",
                    "uuid": "151234234",
                    "distinct_id": "abc123",
                    "timestamp": "2024-10-24T23:03:50.941Z",
                    "properties": {
                        "$is_identified": True,
                        "$app_build": "1.0.0",
                        "$app_version": "2.0",
                        "$app_name": "PostHog",
                        "utm_campaign": "test1",
                        "utm_content": "test2",
                        "utm_medium": "test3",
                        "utm_source": "test4",
                        "utm_term": "test5",
                        "$device_id": "test6",
                        "$device_manufacturer": "test7",
                        "$device_model": "test8",
                        "$os_name": "test9",
                        "$os_version": "test10",
                        "$device_type": "test11",
                        "$ip": "test12",
                        "$browser_language": "test13",
                        "$os": "test14",
                        "$referrer": "test15",
                        "$screen_height": "test16",
                        "$screen_width": "test17",
                        "$geoip_time_zone": "test18",
                        "$raw_user_agent": "test19",
                        "$current_url": "https://hedgebox.net/faq?billing",
                        "$pathname": "/faq",
                        "title": "Hedgebox",
                    },
                },
            },
        )

        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://api.june.so/sdk/page",
                {
                    "method": "POST",
                    "headers": {
                        "Authorization": "Basic abcdef123456",
                        "Content-Type": "application/json",
                    },
                    "body": {
                        "properties": {
                            "url": "https://hedgebox.net/faq?billing",
                            "path": "/faq",
                            "title": "Hedgebox",
                            "referrer": "test15",
                            "search": "?billing",
                        },
                        "traits": {"name": "Max AI", "email": "max@posthog.com"},
                        "timestamp": "2024-10-24T23:03:50.941Z",
                        "context": {
                            "app": {"build": "1.0.0", "version": "2.0", "name": "PostHog"},
                            "campaign": {
                                "name": "test1",
                                "content": "test2",
                                "medium": "test3",
                                "source": "test4",
                                "term": "test5",
                            },
                            "device": {
                                "id": "test6",
                                "manufacturer": "test7",
                                "model": "test8",
                                "name": "test9",
                                "version": "test10",
                                "type": "test11",
                            },
                            "os": {"name": "test14", "version": "test10"},
                            "referrer": {"url": "test15"},
                            "screen": {
                                "height": "test16",
                                "width": "test17",
                            },
                            "ip": "test12",
                            "locale": "test13",
                            "timezone": "test18",
                            "userAgent": "test19",
                        },
                        "messageId": "151234234",
                        "userId": "abc123",
                    },
                },
            )
        )

    def test_body_includes_all_properties_if_set(self):
        self.run_function(
            inputs=create_inputs(include_all_properties=True),
            globals={
                "event": {
                    "event": "$pageview",
                    "uuid": "151234234",
                    "distinct_id": "abc123",
                    "timestamp": "2024-10-24T23:03:50.941Z",
                    "properties": {
                        "$is_identified": True,
                        "$current_url": "https://hedgebox.net/faq?billing",
                        "$pathname": "/faq",
                        "title": "Hedgebox",
                    },
                },
            },
        )

        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://api.june.so/sdk/page",
                {
                    "method": "POST",
                    "headers": {
                        "Authorization": "Basic abcdef123456",
                        "Content-Type": "application/json",
                    },
                    "body": {
                        "properties": {
                            "url": "https://hedgebox.net/faq?billing",
                            "path": "/faq",
                            "title": "Hedgebox",
                            "search": "?billing",
                        },
                        "traits": {"name": "Max AI", "email": "max@posthog.com", "title": "Hedgebox"},
                        "timestamp": "2024-10-24T23:03:50.941Z",
                        "context": {
                            "app": {},
                            "campaign": {},
                            "device": {},
                            "os": {},
                            "referrer": {},
                            "screen": {},
                        },
                        "messageId": "151234234",
                        "userId": "abc123",
                    },
                },
            )
        )

        self.run_function(
            inputs=create_inputs(include_all_properties=False),
            globals={
                "event": {
                    "event": "$pageview",
                    "uuid": "151234234",
                    "distinct_id": "abc123",
                    "timestamp": "2024-10-24T23:03:50.941Z",
                    "properties": {
                        "$is_identified": True,
                        "$current_url": "https://hedgebox.net/faq?billing",
                        "$pathname": "/faq",
                        "title": "Hedgebox",
                    },
                },
            },
        )

        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://api.june.so/sdk/page",
                {
                    "method": "POST",
                    "headers": {
                        "Authorization": "Basic abcdef123456",
                        "Content-Type": "application/json",
                    },
                    "body": {
                        "properties": {
                            "url": "https://hedgebox.net/faq?billing",
                            "path": "/faq",
                            "title": "Hedgebox",
                            "search": "?billing",
                        },
                        "traits": {
                            "name": "Max AI",
                            "email": "max@posthog.com",
                        },
                        "timestamp": "2024-10-24T23:03:50.941Z",
                        "context": {
                            "app": {},
                            "campaign": {},
                            "device": {},
                            "os": {},
                            "referrer": {},
                            "screen": {},
                        },
                        "messageId": "151234234",
                        "userId": "abc123",
                    },
                },
            )
        )

    def test_automatic_type_mapping(self):
        for event_name, expected_type in [
            ("$identify", "identify"),
            ("$set", "identify"),
            ("$pageview", "page"),
            ("$screen", "page"),
            ("$autocapture", "track"),
            ("custom", "track"),
        ]:
            self.run_function(
                inputs=create_inputs(),
                globals={
                    "event": {"event": event_name, "properties": {"$current_url": "https://example.com"}},
                },
            )

            assert self.get_mock_fetch_calls()[0][0] == "https://api.june.so/sdk/" + expected_type

    def test_identified_tracking(self):
        self.run_function(
            inputs=create_inputs(),
            globals={
                "event": {
                    "event": "$pageview",
                    "uuid": "151234234",
                    "distinct_id": "abc123",
                    "timestamp": "2024-10-24T23:03:50.941Z",
                    "properties": {
                        "$is_identified": True,
                        "$current_url": "https://hedgebox.net/faq?billing",
                        "$pathname": "/faq",
                        "title": "Hedgebox",
                    },
                },
            },
        )

        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://api.june.so/sdk/page",
                {
                    "method": "POST",
                    "headers": {
                        "Authorization": "Basic abcdef123456",
                        "Content-Type": "application/json",
                    },
                    "body": {
                        "properties": {
                            "url": "https://hedgebox.net/faq?billing",
                            "path": "/faq",
                            "title": "Hedgebox",
                            "search": "?billing",
                        },
                        "traits": {"name": "Max AI", "email": "max@posthog.com"},
                        "timestamp": "2024-10-24T23:03:50.941Z",
                        "context": {
                            "app": {},
                            "campaign": {},
                            "device": {},
                            "os": {},
                            "referrer": {},
                            "screen": {},
                        },
                        "messageId": "151234234",
                        "userId": "abc123",
                    },
                },
            )
        )

        self.run_function(
            inputs=create_inputs(),
            globals={
                "event": {
                    "event": "$pageview",
                    "uuid": "151234234",
                    "distinct_id": "abc123",
                    "timestamp": "2024-10-24T23:03:50.941Z",
                    "properties": {
                        "$is_identified": False,
                        "$current_url": "https://hedgebox.net/faq?billing",
                        "$pathname": "/faq",
                        "title": "Hedgebox",
                        "$anon_distinct_id": "12345678abc",
                    },
                },
            },
        )

        assert self.get_mock_fetch_calls()[0] == snapshot(
            (
                "https://api.june.so/sdk/page",
                {
                    "method": "POST",
                    "headers": {
                        "Authorization": "Basic abcdef123456",
                        "Content-Type": "application/json",
                    },
                    "body": {
                        "properties": {
                            "url": "https://hedgebox.net/faq?billing",
                            "path": "/faq",
                            "title": "Hedgebox",
                            "search": "?billing",
                        },
                        "traits": {"name": "Max AI", "email": "max@posthog.com"},
                        "timestamp": "2024-10-24T23:03:50.941Z",
                        "context": {
                            "app": {},
                            "campaign": {},
                            "device": {},
                            "os": {},
                            "referrer": {},
                            "screen": {},
                        },
                        "messageId": "151234234",
                        "anonymousId": "abc123",
                    },
                },
            )
        )
