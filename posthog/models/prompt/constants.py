prompts_config = [
    {
        "key": "start-flow",  # sequence key
        "prompts": [
            {
                "step": 0,  # step in the flow
                "type": "tooltip",  # type of prompt, for now only tooltip
                "title": "Get more from PostHog",  # title of the prompt
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
                        "url": "https://posthog.com/blog/track-your-website-with-posthog",
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
                        "url": "https://posthog.com/blog/events-you-should-track-with-posthog",
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
                        "url": "https://posthog.com/blog/essential-posthog-apps",
                        "label": "Getting started: Your five essential PostHog apps",
                    }
                ],
                "reference": "help-button",
            },
        ],
        "rule": {
            "path": {"must_match": ["/*"], "exclude": ["/ingestion", "/ingestion/*"]},
            "must_be_completed": ["start-flow"],
            "requires_opt_in": True,
        },
        "type": "one-off",
    },
    {
        "key": "session-recording-playlist-announcement",
        "prompts": [
            {
                "step": 0,
                "type": "tooltip",
                "title": "Save your filters as playlists!",
                "text": "You can now save your search as a playlist which will keep up to date as new recordings come in matching the filters you set. Sharing with your team has never been easier!",
                "placement": "bottom-start",
                "reference": "save-recordings-playlist-button",
            }
        ],
        "rule": {"path": {"must_match": ["/recordings/recent"]}},
        "type": "one-off",
    },
]
