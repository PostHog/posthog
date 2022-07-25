from typing import Any, Dict, List

from django.db import models
from django.utils import timezone


class PromptSequenceState(models.Model):
    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "person", "key"], name="unique sequence key for person for team")
        ]

    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    person: models.ForeignKey = models.ForeignKey("Person", on_delete=models.CASCADE)
    key: models.CharField = models.CharField(max_length=400)

    last_updated_at: models.DateTimeField = models.DateTimeField(default=timezone.now)
    step: models.IntegerField = models.IntegerField(default=1)
    completed: models.BooleanField = models.BooleanField(default=False)
    dismissed: models.BooleanField = models.BooleanField(default=False)


class PromptSequence(models.Model):
    class Meta:
        constraints = [models.UniqueConstraint(fields=["team", "key"], name="unique sequence key for team")]

    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    key: models.CharField = models.CharField(max_length=400)

    prompts: models.JSONField = models.JSONField(default=list)
    rule: models.JSONField = models.JSONField(default=dict)
    type: models.CharField = models.CharField(max_length=400)


experimentConfig = [
    {
        "key": "experiment-events-product-tour",
        "prompts": [
            {
                "step": 0,
                "type": "tooltip",
                "text": "Welcome! We'd like to give you a quick tour!",
                "placement": "top-start",
                "buttons": [{"action": "skip", "label": "Skip tutorial"}],
                "reference": "experiment-events-product-tour",
                "icon": "live-events",
            },
            {
                "step": 1,
                "type": "tooltip",
                "text": "Here you can see all events from the past 12 months. Things look a bit quiet, so let's turn on automatic refresh to see events in real-time.",
                "placement": "top-start",
                "reference": "experiment-events-product-tour",
                "icon": "live-events",
            },
            {
                "step": 2,
                "type": "tooltip",
                "text": "If you aren't seeing the data you expect then you can always ask for help. For now, lets analyze some data. Click 'Dashboards' in the sidebar.",
                "placement": "top-start",
                "buttons": [{"url": "https://posthog.com/questions", "label": "Ask for help"}],
                "icon": "live-events",
                "reference": "experiment-events-product-tour",
            },
        ],
        "rule": {"path": "/events"},
        "type": "product-tour",
    },
    {
        "key": "experiment-dashboards-product-tour",
        "prompts": [
            {
                "step": 0,
                "type": "tooltip",
                "text": "In PostHog, you analyse data with Insights which can be added to Dashboards to aid collaboration. Let's create a new Dashboard by selecting 'New Dashboard'. ",
                "placement": "top-start",
                "icon": "dashboard",
                "reference": "experiment-dashboards-product-tour",
            }
        ],
        "rule": {"path": "/dashboard"},
        "type": "product-tour",
    },
    {
        "key": "experiment-new-dashboard-product-tour",
        "prompts": [
            {
                "step": 0,
                "type": "tooltip",
                "text": "From here, you can control access to this dashboard. In the options menu you can also subscribe to dashboards, to get updates via Email or Slack. For now, let's add an insight.",
                "placement": "top-start",
                "reference": "experiment-new-dashboard-product-tour-1",
                "icon": "dashboard",
            }
        ],
        "rule": {"path": "/dashboard/*"},
        "type": "product-tour",
    },
    {
        "key": "experiment-new-insight-product-tour",
        "prompts": [
            {
                "step": 0,
                "type": "tooltip",
                "text": "Here you can select the type of insight you want and the data you want to visualize. You can find out how more insight types in the user guides.",
                "placement": "top-start",
                "buttons": [{"url": "https://posthog.com/docs/user-guides/insights", "label": "Open Insights docs"}],
                "icon": "insight",
                "reference": "experiment-new-insight-product-tour",
            },
            {
                "step": 1,
                "type": "tooltip",
                "text": "For now, try adding more steps or filters, then name the insight and save it to the dashboard. You can have unlimited insights, so names and tags help you stay organized.",
                "placement": "top-start",
                "icon": "insight",
                "reference": "experiment-new-insight-product-tour",
            },
        ],
        "rule": {"path": "/insights/new"},
        "type": "product-tour",
    },
    {
        "key": "experiment-dashboard-product-tour",
        "prompts": [
            {
                "step": 0,
                "type": "tooltip",
                "text": "Uh oh! This dashboard isn't refreshing automatically. We can manually update it, or we can click here to make it refresh at regular intervals.",
                "placement": "top-start",
                "reference": "experiment-dashboard-product-tour-1",
                "icon": "dashboard",
            },
            {
                "step": 1,
                "type": "tooltip",
                "text": "That covers the basics, but if you want to learn about tools such as Feature Flags, Experiments, Apps or more then visit our Docs, or ask us a question. We hope you enjoy using PostHog!",
                "placement": "top-start",
                "buttons": [{"url": "https://posthog.com/docs", "label": "Open Docs"}],
                "reference": "experiment-dashboard-product-tour-1",
                "icon": "dashboard",
            },
        ],
        "rule": {"path": "/dashboard/*"},
        "type": "product-tour",
    },
]

# Return prompts
def get_active_prompt_sequences() -> List[Dict[str, Any]]:

    # we're running an experiment with a hard coded list of prompts
    all_prompt_sequences: List = experimentConfig

    return all_prompt_sequences
