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
    step: models.IntegerField = models.IntegerField(default=0)
    completed: models.BooleanField = models.BooleanField(default=False)
    dismissed: models.BooleanField = models.BooleanField(default=False)


experiment_config = [
    {
        "key": "start-flow",  # sequence key
        "prompts": [
            {
                "step": 0,  # step in the flow
                "type": "tooltip",  # type of prompt, for now only tooltip
                "text": "Welcome to PostHog! We’d like to give you a quick overview of how things work. You can skip this introduction at any time, or restart it from the help menu.",
                "placement": "bottom-start",
                "buttons": [
                    {"action": "skip", "label": "Skip tutorial"},
                    {"action": "run-tutorial", "label": "Show me tips"},
                ],  # buttons, can open external urls or trigger actions
                "reference": "help-button",  # should match a `data-tooltip` reference to attach to a component
                "icon": "messages",  # tbd if makes sense to add to the config, displays a different icon in the tooltips
            },
        ],
        "rule": {
            "path": "/*"
        },  # currently two rules enabled: `path` triggers the sequence by pathname, using wildcard matching; `must_be_completed`: allows to run a sequence only if others are completed;
        "type": "one-off",  # can be used to toggle different behaviors in the frontend
    },
    {
        "key": "home-product-tour",
        "prompts": [
            {
                "step": 0,
                "type": "tooltip",
                "text": "This is the home page, where you can see the most recent insights, data and any pinned dashboards. You can also invite as many team members as you like, for free!",
                "placement": "top-start",
                "reference": "invite-members-button",
                "icon": "home",
            },
            {
                "step": 1,
                "type": "tooltip",
                "text": "If you have multiple products, it’s wise to set them up as separate projects so you don’t muddy the data. You can change projects at any time by clicking here.",
                "placement": "bottom-start",
                "reference": "project-button",
                "icon": "home",
            },
            {
                "step": 2,
                "type": "tooltip",
                "text": "Want to track how many events you’ve ingested this month? You can access billing information and manage your subscription here.",
                "placement": "top-start",
                "icon": "home",
                "reference": "profile-button",
            },
        ],
        "rule": {"path": "/home", "must_be_completed": ["start-flow"]},
        "type": "product-tour",
    },
    {
        "key": "dashboards-product-tour",
        "prompts": [
            {
                "step": 0,
                "type": "tooltip",
                "text": "Dashboards are a great way to look at multiple insights quickly. Here, you can create, edit or duplicate dashboards with ease.",
                "placement": "top-start",
                "reference": "dashboards-table",
                "icon": "dashboard",
            },
        ],
        "rule": {"path": "/dashboard", "must_be_completed": ["start-flow"]},
        "type": "product-tour",
    },
    {
        "key": "single-dashboard-product-tour",
        "prompts": [
            {
                "step": 0,
                "type": "tooltip",
                "text": "Dashboards are a useful way to collaborate. Use this options menu to export dashboard snapshots, or set up automatic subscriptions to tools such as Slack.",
                "placement": "top-start",
                "reference": "dashboard-three-dots-options-menu",
                "icon": "dashboard",
            },
            {
                "step": 1,
                "type": "tooltip",
                "text": "Tags are used across PostHog to help you stay organized. As you create more dashboards, titles and tags becomes even more useful.",
                "placement": "top-start",
                "reference": "dashboard-tags",
                "icon": "dashboard",
            },
        ],
        "rule": {"path": "/dashboard/*", "must_be_completed": ["start-flow"]},
        "type": "product-tour",
    },
    {
        "key": "insight-product-tour",
        "prompts": [
            {
                "step": 0,
                "type": "tooltip",
                "text": "Insights are how you analyze data. You can select from many insight types, such as funnels or user paths. Find out more about each in User Guides!",
                "buttons": [{"url": "https://posthog.com/docs/user-guides/insights", "label": "Open User Guides"}],
                "placement": "top-start",
                "reference": "insight-view",
                "icon": "insight",
            },
            {
                "step": 1,
                "type": "tooltip",
                "text": "Filters enable you to exclude unwanted data from an insight based on any insight. Want to create a filter for internal users? Check this tutorial!",
                "buttons": [
                    {"url": "https://posthog.com/tutorials/filter-internal-users", "label": "Insight Filters tutorial"}
                ],
                "placement": "top-start",
                "reference": "insight-view",
                "icon": "insight",
            },
            {
                "step": 2,
                "type": "tooltip",
                "text": "Don’t forget to save your insight! Once it’s saved you can add it to a dashboard, share, embed, or export it - or set up subscriptions in tools such as Slack.",
                "placement": "top-start",
                "reference": "insight-save-button",
                "icon": "insight",
            },
        ],
        "rule": {"path": "/insights/*", "must_be_completed": ["start-flow"]},
        "type": "product-tour",
    },
    {
        "key": "new-insight-product-tour",
        "prompts": [
            {
                "step": 0,
                "type": "tooltip",
                "text": "Don’t forget to save your insight! Once it’s saved you can add it to a dashboard, share, embed, or export it - or set up subscriptions in tools such as Slack.",
                "placement": "top-start",
                "reference": "insight-save-button",
                "icon": "insight",
            },
        ],
        "rule": {"path": "/insights/new", "must_be_completed": ["start-flow"]},
        "type": "product-tour",
    },
    {
        "key": "recordings-product-tour",
        "prompts": [
            {
                "step": 0,
                "type": "tooltip",
                "text": "This is a list of session recordings from your users. PostHog is careful about what it records, but you can also set your own privacy rules to protect users.",
                "buttons": [
                    {
                        "url": "https://posthog.com/docs/user-guides/recordings#ignoring-sensitive-elements",
                        "label": "Open Privacy Rules guide",
                    }
                ],
                "placement": "top-start",
                "reference": "session-recording-table",
                "icon": "recordings",
            },
        ],
        "rule": {"path": "/recordings", "must_be_completed": ["start-flow"]},
        "type": "product-tour",
    },
    {
        "key": "single-recording-product-tour",
        "prompts": [
            {
                "step": 0,
                "type": "tooltip",
                "text": "Here you can see a list of all the events this user triggered during a session. Click any session to jump to that point and watch how users behave.",
                "placement": "top-start",
                "reference": "recording-event-list",
                "icon": "recordings",
            },
            {
                "step": 0,
                "type": "tooltip",
                "text": "User recordings can be quite long, so by default we’ll skip periods of inactivity. You can also speed up recordings, or skip to particular events using this timeline.",
                "placement": "top-start",
                "reference": "recording-player",
                "icon": "recordings",
            },
        ],
        "rule": {"path": "/recordings?*", "must_be_completed": ["start-flow"]},
        "type": "product-tour",
    },
    {
        "key": "feature-flags-product-tour",
        "prompts": [
            {
                "step": 0,
                "type": "tooltip",
                "text": "Here you’ll see a list of any feature flags you have. You can also use the History tab to see info such as changes to how a flag is rolled out.",
                "placement": "top-start",
                "reference": "feature-flag-table",
                "icon": "feature-flags",
            },
        ],
        "rule": {"path": "/feature_flags", "must_be_completed": ["start-flow"]},
        "type": "product-tour",
    },
    {
        "key": "new-feature-flag-product-tour",
        "prompts": [
            {
                "step": 0,
                "type": "tooltip",
                "text": "Once you’ve created a flag as per the integration instructions, you can set release conditions to define who the flag is released to.",
                "placement": "top-start",
                "reference": "feature-flag-release-conditions",
                "icon": "feature-flags",
            },
            {
                "step": 1,
                "type": "tooltip",
                "text": "Once you’ve created a flag, don’t forget to save it. New flags will default to enabled, so if you don’t want to release yet then be sure to disable it for now.",
                "placement": "top-start",
                "reference": "feature-flag-enabled-toggle",
                "icon": "feature-flags",
            },
        ],
        "rule": {"path": "/feature_flags/new", "must_be_completed": ["start-flow"]},
        "type": "product-tour",
    },
    {
        "key": "experiments-product-tour",
        "prompts": [
            {
                "step": 0,
                "type": "tooltip",
                "text": "How do experiments and feature flags differ? In short, experiments are for testing changes, while feature flags are for phased roll-outs. There’s a lot to discover with experiments, so we recommend reading the docs.",
                "buttons": [
                    {"url": "https://posthog.com/docs/user-guides/experimentation", "label": "Open Experiments docs"}
                ],
                "placement": "top-start",
                "reference": "experiments-table",
                "icon": "experiments",
            },
        ],
        "rule": {"path": "/experiments", "must_be_completed": ["start-flow"]},
        "type": "product-tour",
    },
    {
        "key": "new-experiment-product-tour",
        "prompts": [
            {
                "step": 0,
                "type": "tooltip",
                "text": "The success of experiments is based on tracking performance against a specified goal. Here, you can specify the goal as well as which users are entered in the experiment.",
                "placement": "top-start",
                "reference": "experiment-goal-type",
                "icon": "experiments",
            },
            {
                "step": 1,
                "type": "tooltip",
                "text": "To help you build better experiments, we estimate how long it will take to get statistically significant results. You can read more about how we determine this in the docs.",
                "buttons": [
                    {
                        "url": "https://posthog.com/docs/user-guides/experimentation#advanced-whats-under-the-hood",
                        "label": "Read more in the docs",
                    }
                ],
                "placement": "top-start",
                "reference": "experiment-preview",
                "icon": "experiments",
            },
        ],
        "rule": {"path": "/experiments/new", "must_be_completed": ["start-flow"]},
        "type": "product-tour",
    },
    {
        "key": "web-performance-product-tour",
        "prompts": [
            {
                "step": 0,
                "type": "tooltip",
                "text": "PostHog doesn’t capture performance info on all events, but when it does you can see it here. You can also use Filters to find specific events, if needed.",
                "placement": "top-start",
                "reference": "web-performance-table",
                "icon": "web-performance",
            },
        ],
        "rule": {"path": "/web-performance", "must_be_completed": ["start-flow"]},
        "type": "product-tour",
    },
    {
        "key": "single-web-performance-product-tour",
        "prompts": [
            {
                "step": 0,
                "type": "tooltip",
                "text": "Sometimes it can be helpful to get more context when looking at performance issues. Click here to go straight to a session recording of this event.",
                "placement": "top-start",
                "reference": "web-performance-chart",
                "icon": "web-performance",
            },
        ],
        "rule": {"path": "/web-performance/*", "must_be_completed": ["start-flow"]},
        "type": "product-tour",
    },
    {
        "key": "live-events-product-tour",
        "prompts": [
            {
                "step": 0,
                "type": "tooltip",
                "text": "Here you can see all events from the past 12 months. If things look a bit quiet, turn on automatic refresh to see events as they come in.",
                "placement": "top-start",
                "reference": "live-events-refresh-toggle",
                "icon": "live-events",
            },
            {
                "step": 1,
                "type": "tooltip",
                "text": "If you’re not seeing the data you expect here, you may have an event ingestion issue. You can always use the help menu to ask for assistance, or go to the docs.",
                "buttons": [{"url": "https://posthog.com/docs/integrate", "label": "Open the docs"}],
                "placement": "top-start",
                "reference": "help-button",
                "icon": "live-events",
            },
        ],
        "rule": {"path": "/events", "must_be_completed": ["start-flow"]},
        "type": "product-tour",
    },
    {
        "key": "data-management-product-tour",
        "prompts": [
            {
                "step": 0,
                "type": "tooltip",
                "text": "Here you can see every event PostHog has ingested, as well as how often it’s been used for insights in the last 30 days. Click any event to get more information.",
                "placement": "top-start",
                "reference": "data-management-table",
                "icon": "data-management",
            },
        ],
        "rule": {"path": "/data-management/events", "must_be_completed": ["start-flow"]},
        "type": "product-tour",
    },
    {
        "key": "data-management-event-product-tour",
        "prompts": [
            {
                "step": 0,
                "type": "tooltip",
                "text": "You can click ‘Edit’ to add tags or descriptions to events, which makes it easier for other users to build accurate insights.",
                "placement": "top-start",
                "reference": "data-management-event-edit-button",
                "icon": "data-management",
            },
        ],
        "rule": {"path": "/data-management/events/*", "must_be_completed": ["start-flow"]},
        "type": "product-tour",
    },
    {
        "key": "persons-product-tour",
        "prompts": [
            {
                "step": 0,
                "type": "tooltip",
                "text": "Here you can see every user PostHog has tracked. Unidentified users are assigned an ID key, while identified users are listed by their email address.",
                "placement": "top-start",
                "reference": "persons-table",
                "icon": "persons",
            },
        ],
        "rule": {"path": "/persons", "must_be_completed": ["start-flow"]},
        "type": "product-tour",
    },
    {
        "key": "single-person-product-tour",
        "prompts": [
            {
                "step": 0,
                "type": "tooltip",
                "text": "This page collects all information PostHog has on this individual, including session records and any cohorts they belong to.",
                "placement": "top-start",
                "reference": "persons-tabs",
                "icon": "persons",
            },
            {
                "step": 1,
                "type": "tooltip",
                "text": "Sometimes you may capture a user’s info twice, or you may need to delete records of an individual. In either situation, PostHog can do that.",
                "placement": "top-start",
                "reference": "person-split-merge-button",
                "icon": "persons",
            },
        ],
        "rule": {"path": "/person/*", "must_be_completed": ["start-flow"]},
        "type": "product-tour",
    },
    {
        "key": "cohorts-product-tour",
        "prompts": [
            {
                "step": 0,
                "type": "tooltip",
                "text": "Cohorts, listed here, are collections of users who have something in common — such as an event, behaviour, or property.",
                "placement": "top-start",
                "reference": "cohorts-table",
                "icon": "cohorts",
            },
        ],
        "rule": {"path": "/cohorts", "must_be_completed": ["start-flow"]},
        "type": "product-tour",
    },
    {
        "key": "new-cohort-product-tour",
        "prompts": [
            {
                "step": 0,
                "type": "tooltip",
                "text": "Cohorts can be either dynamic, or static. Dynamic cohorts are great for on-going analysis, as new matching users are automatically added. Static cohorts must be manually updated.",
                "placement": "top-start",
                "reference": "cohorts-type",
                "icon": "cohorts",
            },
        ],
        "rule": {"path": "/cohorts/new", "must_be_completed": ["start-flow"]},
        "type": "product-tour",
    },
    {
        "key": "annotations-product-tour",
        "prompts": [
            {
                "step": 0,
                "type": "tooltip",
                "text": "Annotations are a useful way to add context to your historical data, so you can see when major changes, such as a product release, happened.",
                "placement": "top-start",
                "reference": "annotations-table",
                "icon": "annotations",
            },
            {
                "step": 1,
                "type": "tooltip",
                "text": "Annotations can be really helpful later down the road, especially for new team members. Getting into the habit of adding annotations will help you get the most out of PostHog.",
                "placement": "top-start",
                "reference": "annotations-new-button",
                "icon": "annotations",
            },
        ],
        "rule": {"path": "/annotations", "must_be_completed": ["start-flow"]},
        "type": "product-tour",
    },
    {
        "key": "apps-product-tour",
        "prompts": [
            {
                "step": 0,
                "type": "tooltip",
                "text": "PostHog has a growing library of apps to help you import, export or transform data. Once you’ve installed an app, click the blue gear icon to configure it.",
                "placement": "top-start",
                "reference": "apps-tabs",
                "icon": "apps",
            },
            {
                "step": 1,
                "type": "tooltip",
                "text": "Apps in PostHog function as a chain, with one acting after another before data is stored. Here, you can drag enabled apps to run in any order you’d like.",
                "placement": "top-start",
                "reference": "apps-tabs",
                "icon": "apps",
            },
            {
                "step": 2,
                "type": "tooltip",
                "text": "Can’t find the app you need? Everything on PostHog is open source, so use the Advanced tab to get started building and releasing your own apps to the community!",
                "placement": "top-start",
                "reference": "apps-tabs",
                "icon": "apps",
            },
        ],
        "rule": {"path": "/project/apps", "must_be_completed": ["start-flow"]},
        "type": "product-tour",
    },
    {
        "key": "toolbar-product-tour",
        "prompts": [
            {
                "step": 0,
                "type": "tooltip",
                "text": "If you’re signed in to PostHog, the toolbar enables you to make some changes right within your product. Just authorize a domain, enable the toolbar and away you go!",
                "placement": "top-start",
                "reference": "toolbar-authorized-toggle",
                "icon": "apps",
            },
        ],
        "rule": {"path": "/toolbar", "must_be_completed": ["start-flow"]},
        "type": "product-tour",
    },
]

# Return prompts
def get_active_prompt_sequences() -> List[Dict[str, Any]]:

    # we're running an experiment with a hard coded list of prompts
    return experiment_config
