from typing import Any, Dict, List

from django.db import models
from django.utils import timezone


class UserPromptSequenceState(models.Model):
    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "key"], name="unique sequence key for user")]

    user: models.ForeignKey = models.ForeignKey("User", on_delete=models.CASCADE)
    key: models.CharField = models.CharField(max_length=400)

    last_updated_at: models.DateTimeField = models.DateTimeField(default=timezone.now)
    step: models.IntegerField = models.IntegerField(default=0)
    completed: models.BooleanField = models.BooleanField(default=False)
    dismissed: models.BooleanField = models.BooleanField(default=False)


prompts_config = [
    {
        "key": "start-flow",  # sequence key
        "prompts": [
            {
                "step": 0,  # step in the flow
                "type": "tooltip",  # type of prompt, for now only tooltip
                "title": "Welcome to PostHog!",  # title of the prompt
                "text": "We have prepared a list of suggestions and resources to improve your experience with the tool. You can access it at any time by clicking on the question mark icon in the top right corner of the screen, and then selecting 'How to be successful with PostHog'.",
                "placement": "bottom-start",
                "buttons": [
                    {"action": "activation-checklist", "label": "Show me suggestions"},
                ],  # buttons, can open external urls or trigger actions
                "reference": "help-button",  # should match a `data-tooltip` reference to attach to a component
                # "icon": "trend-up",  # tbd if makes sense to add to the config, displays a different icon in the tooltips
            }
        ],
        "rule": {
            "path": {"must_match": ["/*"], "exclude": ["/ingestion", "/ingestion/*"]}
        },  # currently two rules enabled: `path` triggers the sequence by pathname, using wildcard matching; `must_be_completed`: allows to run a sequence only if others are completed;
        "type": "one-off",  # can be used to toggle different behaviors in the frontend
    },
    {
        "key": "activation-checklist",
        "prompts": [
            {
                "step": 0,
                "type": "tooltip",
                "title": "Track your marketing websites",
                "text": "PostHog may have been built for product analytics, but that doesn’t mean you can only deploy it on your core product — you can also use it to gather analytics from your marketing website too.",
                "placement": "bottom-start",
                "buttons": [
                    {
                        "url": "https://posthog.com/blog/how-and-why-track-your-website-with-posthog",
                        "label": "How (and why) to track your website with PostHog",
                    }
                ],
                "reference": "help-button",
            },
            {
                "step": 1,
                "type": "tooltip",
                "title": "Start tracking the right events",
                "text": "If you haven’t used product analytics before, it can be tricky to know which events you should start tracking first. This guide outlines five of the most essential events we recommend tracking with PostHog.",
                "placement": "bottom-start",
                "buttons": [
                    {
                        "url": "https://posthog.com/blog/five-events-everyone-should-track-with-product-analytics",
                        "label": "Five events all teams should track with PostHog",
                    }
                ],
                "reference": "help-button",
            },
            {
                "step": 2,
                "type": "tooltip",
                "title": "Introduce PostHog to your teams",
                "text": "While PostHog is obviously useful for product managers, engineers and analysts, there’s a lot it can do for other teams too — including marketing and customer success.",
                "placement": "bottom-start",
                "buttons": [
                    {
                        "url": "https://posthog.com/blog/analytics-tips-for-marketing-teams",
                        "label": "Five analytics ideas for Marketing teams using PostHog",
                    },
                    {
                        "url": "https://posthog.com/blog/analytics-tips-for-customer-success-teams",
                        "label": "Five essential tips for Customer Success teams on PostHog",
                    },
                ],
                "reference": "help-button",
            },
            {
                "step": 3,
                "type": "tooltip",
                "title": "Enrich your PostHog experience with Apps",
                "text": "PostHog apps are a powerful, but ill-defined part of the platform. They’re powerful because they can do almost anything — and they’re ill-defined because they do almost anything.",
                "placement": "bottom-start",
                "buttons": [
                    {
                        "url": "https://posthog.com/blog/five-essential-posthog-apps.md",
                        "label": "Getting started: Your five essential PostHog apps",
                    }
                ],
                "reference": "help-button",
            },
        ],
        "rule": {
            "path": {"must_match": ["/*"], "exclude": ["/ingestion", "/ingestion/*"]},
            "must_be_completed": ["start-flow"],
        },
        "type": "one-off",
    },
]

# Return prompts
def get_active_prompt_sequences() -> List[Dict[str, Any]]:

    # we're running an experiment with a hard coded list of prompts
    return prompts_config
