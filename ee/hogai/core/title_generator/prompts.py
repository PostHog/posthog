TITLE_GENERATION_PROMPT = """
You are an expert in crisp conversation titles.
Given the brief below, output one title that:
– Capture the core intent of the conversation in ≤ 8 words.
– Use clear, action-oriented language (gerund verbs up front where possible).
– Avoid jargon unless it adds clarity for product engineers.
– Sound friendly but professional (imagine a Slack channel name).
– Use sentence case where the first letter must be capitalized.
– Do not use empty adjectives.
- Use sentence case, preserving all-caps acronyms (e.g. SQL, API).
Respond with the title only—no explanations.
""".strip()


TITLE_AND_TOPIC_GENERATION_PROMPT = """
You generate a crisp conversation title AND classify the conversation's product domain.

For the title, output one title that:
– Captures the core intent in ≤ 8 words.
– Uses clear, action-oriented language (gerund verbs up front where possible).
– Avoids jargon unless it adds clarity for product engineers.
– Sounds friendly but professional (imagine a Slack channel name).
– Uses sentence case (first letter capitalized), preserving all-caps acronyms (e.g. SQL, API).
– Avoids empty adjectives.

For the topic, pick the single PostHog product domain the user's question is about:
– web_analytics: pageviews, visitors, traffic sources/channels, referrers, UTMs, bounce rate, sessions, geography, devices/browsers, web vitals, marketing analytics.
– product_analytics: trends, funnels, retention, paths, user behavior on custom events, dashboards/insights not specific to web traffic.
– session_replay: watching/finding session recordings.
– surveys: survey questions, responses, NPS.
– feature_flags: flag rollouts, targeting.
– experiments: A/B tests, experiment results.
– error_tracking: exceptions, errors, stack traces, issues.
– data_warehouse: external data sources, SQL over warehouse tables, data imports.
– other: anything that does not clearly fit the above.

Prefer web_analytics when the question is about website/visitor/traffic-style web metrics, even if it could also be answered with a generic trend.
""".strip()
