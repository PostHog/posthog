import json
from textwrap import dedent

from posthog.test.base import BaseTest

from posthog.models import Action

from ee.hogai.summarizers.actions import ActionSummarizer


class TestActionSummarizer(BaseTest):
    def test_action_summarizer(self):
        json_steps = """
        [{"event":"$pageview","properties":[{"key":"$browser","type":"event","value":["Chrome"],"operator":"exact"},{"key":"$geoip_country_name","type":"person","value":["United States"],"operator":"exact"}],"selector":null,"tag_name":null,"text":null,"text_matching":null,"href":null,"href_matching":"contains","url":"/max","url_matching":"contains"},{"event":"$autocapture","properties":[{"key":"tag_name","type":"element","value":["button"],"operator":"exact"}],"selector":"button","tag_name":null,"text":"Send","text_matching":"contains","href":"/max","href_matching":"exact","url":"\\/max","url_matching":"regex"},{"event":"chat with ai","properties":null,"selector":null,"tag_name":null,"text":null,"text_matching":null,"href":null,"href_matching":"contains","url":null,"url_matching":null}]
        """
        action = Action.objects.create(
            name="Test Action", description="Test Description", steps_json=json.loads(json_steps), team=self.team
        )
        summarizer = ActionSummarizer(action)
        expected_summary = """
            Name: Test Action
            Description: Test Description

            Match group 1: event is `$pageview` AND the URL of event contains `/max` AND event property `$browser` matches exactly `Chrome` AND person property `$geoip_country_name` matches exactly `United States`

            OR

            Match group 2: event is `$autocapture` AND element matches HTML selector `button` AND element text contains `Send` AND element `href` attribute matches exactly `/max` AND the URL of event matches regex `/max` AND element property `tag_name` matches exactly `button`

            OR

            Match group 3: event is `chat with ai`
        """
        self.assertEqual(summarizer.summary, dedent(expected_summary).strip())

    def test_optional_matching_parameters(self):
        steps = [
            {"event": "$pageview", "url": "/max"},
            {"event": "$autocapture", "selector": "button", "text": "Send", "href": "/max", "url": "\\/max"},
        ]
        action = Action.objects.create(
            name="Test Action", description="Test Description", steps_json=steps, team=self.team
        )
        summarizer = ActionSummarizer(action)
        expected_summary = r"""
            Name: Test Action
            Description: Test Description

            Match group 1: event is `$pageview` AND the URL of event contains `/max`

            OR

            Match group 2: event is `$autocapture` AND element matches HTML selector `button` AND element text matches exactly `Send` AND element `href` attribute matches exactly `/max` AND the URL of event contains `\/max`
        """
        self.assertEqual(summarizer.summary, dedent(expected_summary).strip())
