from inline_snapshot import snapshot
from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest
from posthog.cdp.templates.rudderstack.template_rudderstack import template as template_rudderstack


class TestTemplateRudderstack(BaseHogFunctionTemplateTest):
    template = template_rudderstack

    def _inputs(self, **kwargs):
        inputs = {
            "host": "https://hosted.rudderlabs.com",
            "token": "asjdkfasdkjfaskfkjfhdsf",
            "identifier": "a08ff8e1-a5ee-49cc-99e9-564e455c33f0",
        }
        inputs.update(kwargs)
        return inputs

    def test_function_works(self):
        self.run_function(
            inputs=self._inputs(),
            globals={
                "event": {
                    "uuid": "96a04bdc-6021-4120-a3e3-f1988f59ba5f",
                    "timestamp": "2024-08-29T13:40:22.713Z",
                    "distinct_id": "85bcd2e4-d10d-4a99-9dc8-43789b7226a1",
                    "name": "$pageview",
                    "properties": {"$current_url": "https://example.com", "$browser": "Chrome"},
                },
                "person": {"uuid": "a08ff8e1-a5ee-49cc-99e9-564e455c33f0"},
            },
        )

        res = self.get_mock_fetch_calls()[0]
        res[1]["body"]["sentAt"]["dt"] = 1724946899.775266
        assert res == snapshot(
            (
                "https://hosted.rudderlabs.com/v1/batch",
                {
                    "method": "POST",
                    "headers": {
                        "Content-Type": "application/json",
                        "Authorization": "Basic YXNqZGtmYXNka2pmYXNrZmtqZmhkc2Y6",
                    },
                    "body": {
                        "batch": [
                            {
                                "context": {
                                    "app": {"name": "PostHogPlugin"},
                                    "os": {"name": None},
                                    "browser": "Chrome",
                                    "browser_version": None,
                                    "page": {
                                        "host": None,
                                        "url": "https://example.com",
                                        "path": None,
                                        "referrer": None,
                                        "initial_referrer": None,
                                        "referring_domain": None,
                                        "initial_referring_domain": None,
                                    },
                                    "screen": {"height": None, "width": None},
                                    "library": {"name": None, "version": None},
                                    "ip": None,
                                    "active_feature_flags": None,
                                    "token": None,
                                },
                                "channel": "s2s",
                                "messageId": "96a04bdc-6021-4120-a3e3-f1988f59ba5f",
                                "originalTimestamp": "2024-08-29T13:40:22.713Z",
                                "userId": "a08ff8e1-a5ee-49cc-99e9-564e455c33f0",
                                "anonymousId": None,
                                "type": "page",
                                "properties": {
                                    "host": None,
                                    "url": "https://example.com",
                                    "path": None,
                                    "referrer": None,
                                    "initial_referrer": None,
                                    "referring_domain": None,
                                    "initial_referring_domain": None,
                                },
                                "name": None,
                            }
                        ],
                        "sentAt": {"__hogDateTime__": True, "dt": 1724946899.775266, "zone": "UTC"},
                    },
                },
            )
        )

    def test_automatic_action_mapping(self):
        for event_name, expected_action in [
            ("$identify", "identify"),
            ("$set", "identify"),
            ("$pageview", "page"),
            ("$create_alias", "alias"),
            ("$autocapture", "track"),
            ("custom", "track"),
        ]:
            self.run_function(
                inputs=self._inputs(),
                globals={
                    "event": {"name": event_name, "properties": {"url": "https://example.com", "$browser": "Chrome"}},
                },
            )

            assert self.get_mock_fetch_calls()[0][1]["body"]["batch"][0]["type"] == expected_action
