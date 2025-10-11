from __future__ import annotations

# Curated deep-research notebook templates stored as ProseMirror JSON

CURATED_DEEP_RESEARCH_NOTEBOOKS: list[dict] = [
    {
        "id": "dr-conversion-regression-analysis",
        "title": "Conversion regression analysis",
        "content": {
            "type": "doc",
            "content": [
                {
                    "type": "heading",
                    "attrs": {"level": 1},
                    "content": [{"type": "text", "text": "Conversion regression analysis"}],
                },
                {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Objective"}]},
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": "Analyze the drop in conversion rate observed since <date-range>. Identify impacted surfaces, segments, and likely causes.",
                        }
                    ],
                },
                {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Scope"}]},
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": "Users: <e.g., new users vs returning>, Geography: <e.g., US/EU>, Timeframe: <e.g., last 30/90 days>.",
                        }
                    ],
                },
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": "Key flows / features: <e.g., signup → onboarding → first key action>.",
                        }
                    ],
                },
                {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Success metrics"}]},
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": "Primary: overall conversion rate (visit → signup, signup → activation). Secondary: step-level conversion in critical funnels.",
                        }
                    ],
                },
                {
                    "type": "heading",
                    "attrs": {"level": 2},
                    "content": [{"type": "text", "text": "Context & hypotheses"}],
                },
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": "Recent changes: <release / pricing / UX>. Hypotheses: <traffic shift / bug / performance / experiment impact>.",
                        }
                    ],
                },
                {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Questions"}]},
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "- When did the regression start? Is it seasonal?"}],
                },
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "- Which segments (device, geo, source) are most impacted?"}],
                },
                {"type": "paragraph", "content": [{"type": "text", "text": "- Which funnel steps are most affected?"}]},
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": "- Are there concurrent experiment or feature changes correlating with the drop?",
                        }
                    ],
                },
            ],
        },
    },
    {
        "id": "dr-funnel-drop-investigation",
        "title": "Funnel drop investigation",
        "content": {
            "type": "doc",
            "content": [
                {
                    "type": "heading",
                    "attrs": {"level": 1},
                    "content": [{"type": "text", "text": "Funnel drop investigation"}],
                },
                {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Objective"}]},
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": "Locate and quantify the largest drops in the <target funnel> and prioritize fixes for the highest-impact steps.",
                        }
                    ],
                },
                {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Scope"}]},
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": "Timeframe: <e.g., last 14/28 days>. Audience: <e.g., all/new users>. Flow: <define steps>.",
                        }
                    ],
                },
                {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Success metrics"}]},
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": "Step-wise conversion rates, absolute and relative drop, impact in users and %.",
                        }
                    ],
                },
                {
                    "type": "heading",
                    "attrs": {"level": 2},
                    "content": [{"type": "text", "text": "Context & hypotheses"}],
                },
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": "Known issues or UI friction: <list>. Hypotheses: <validation / latency / mobile UX / pricing friction>.",
                        }
                    ],
                },
                {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Questions"}]},
                {"type": "paragraph", "content": [{"type": "text", "text": "- Which step has the largest drop?"}]},
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "- Are certain segments disproportionately affected?"}],
                },
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "- Did the drop coincide with a release/flag rollout?"}],
                },
            ],
        },
    },
    {
        "id": "dr-feature-launch-postmortem",
        "title": "Feature launch postmortem",
        "content": {
            "type": "doc",
            "content": [
                {
                    "type": "heading",
                    "attrs": {"level": 1},
                    "content": [{"type": "text", "text": "Feature launch postmortem"}],
                },
                {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Objective"}]},
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": "Assess adoption, engagement, performance, and downstream impact of the <feature> launch.",
                        }
                    ],
                },
                {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Scope"}]},
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": "Cohorts: exposed vs control (if available). Timeframe: <pre>/<post>. Platforms: <web/iOS/Android>.",
                        }
                    ],
                },
                {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Success metrics"}]},
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": "Adoption (reach, activation), engagement (DAU/WAU, retention on feature), conversion impact.",
                        }
                    ],
                },
                {
                    "type": "heading",
                    "attrs": {"level": 2},
                    "content": [{"type": "text", "text": "Context & hypotheses"}],
                },
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "Rollout flags, known issues, marketing pushes, seasonality."}
                    ],
                },
                {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Questions"}]},
                {"type": "paragraph", "content": [{"type": "text", "text": "- Did the feature move the primary KPI?"}]},
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "- Are there regressions in adjacent flows?"}],
                },
                {"type": "paragraph", "content": [{"type": "text", "text": "- Which segments over/under-performed?"}]},
            ],
        },
    },
    {
        "id": "dr-retention-cohort-deep-dive",
        "title": "Retention cohort deep dive",
        "content": {
            "type": "doc",
            "content": [
                {
                    "type": "heading",
                    "attrs": {"level": 1},
                    "content": [{"type": "text", "text": "Retention cohort deep dive"}],
                },
                {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Objective"}]},
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": "Understand retention by cohort, lifecycle stage, and product usage patterns to identify levers to improve week N retention.",
                        }
                    ],
                },
                {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Scope"}]},
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": "Cohorts: signup week cohorts over last <N> weeks. Segments: device, geo, acquisition source.",
                        }
                    ],
                },
                {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Success metrics"}]},
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "D1/D7/D28 retention, mean vs median activity, stickiness."}],
                },
                {
                    "type": "heading",
                    "attrs": {"level": 2},
                    "content": [{"type": "text", "text": "Context & hypotheses"}],
                },
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "Activation criteria, onboarding changes, pricing/events changes."}
                    ],
                },
                {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Questions"}]},
                {"type": "paragraph", "content": [{"type": "text", "text": "- Which cohorts underperform baseline?"}]},
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "- What usage patterns correlate with higher retention?"}],
                },
                {"type": "paragraph", "content": [{"type": "text", "text": "- Which segments are most sensitive?"}]},
            ],
        },
    },
    {
        "id": "dr-growth-experiment-analysis",
        "title": "Growth experiment analysis",
        "content": {
            "type": "doc",
            "content": [
                {
                    "type": "heading",
                    "attrs": {"level": 1},
                    "content": [{"type": "text", "text": "Growth experiment analysis"}],
                },
                {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Objective"}]},
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": "Evaluate results for the <experiment>, quantify lift, heterogeneity of effects, and guardrail impacts.",
                        }
                    ],
                },
                {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Scope"}]},
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": "Arms: control vs variant(s). Exposure: <flag/rollout>. Timeframe: <start – end>.",
                        }
                    ],
                },
                {
                    "type": "heading",
                    "attrs": {"level": 2},
                    "content": [{"type": "text", "text": "Primary/secondary metrics"}],
                },
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": "Primary: <conversion/retention/revenue>. Secondary: guardrails (latency, error rate, churn, units).",
                        }
                    ],
                },
                {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Questions"}]},
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "- Did we reach power? Is lift statistically significant?"}],
                },
                {"type": "paragraph", "content": [{"type": "text", "text": "- Any segment-level interactions?"}]},
                {"type": "paragraph", "content": [{"type": "text", "text": "- Any negative guardrail movement?"}]},
            ],
        },
    },
]

# Default structure for user-created custom deep research notebooks
# This is NOT seeded into the database, but used when creating custom templates on-demand
DEFAULT_CUSTOM_DEEP_RESEARCH_NOTEBOOK = {
    "id": "dr-custom-research",
    "title": "Custom Deep Research Template",
    "content": {
        "type": "doc",
        "content": [
            {
                "type": "heading",
                "attrs": {"level": 1},
                "content": [{"type": "text", "text": "Custom research"}],
            },
            {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Objective"}]},
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": "What specific question are you trying to answer? What business impact does this have?",
                    }
                ],
            },
            {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Scope"}]},
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": "Users: <which user segments?>"}],
            },
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": "Timeframe: <what time period?>"}],
            },
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": "Features/flows: <which parts of the product?>"}],
            },
            {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Success metrics"}]},
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": "What KPIs define success? Any comparison points or benchmarks?"}],
            },
            {
                "type": "heading",
                "attrs": {"level": 2},
                "content": [{"type": "text", "text": "Context & hypotheses"}],
            },
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "Recent changes, working hypotheses, or constraints to be aware of."}
                ],
            },
            {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Questions"}]},
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": "- What specific questions do you need answered?"}],
            },
        ],
    },
}
