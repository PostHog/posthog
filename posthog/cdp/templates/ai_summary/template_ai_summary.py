from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

# Designed to be used as a workflow action driven by a `schedule` trigger:
# the trigger fires on an RRULE (e.g. hourly), the action runs a HogQL query
# against PostHog, asks an LLM to summarize the result, and posts the summary
# to Slack. The full flow runs as three sequential `fetch` calls — well under
# the per-invocation MAX_ASYNC_STEPS budget of the hog runtime.
template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="beta",
    free=False,
    type="destination",
    id="template-ai-summary",
    name="AI summary to Slack",
    description="Run a HogQL query on a schedule, summarize the result with an LLM, and post the summary to a Slack channel. Pair with a workflow `schedule` trigger to ship periodic AI-generated digests.",
    icon_url="/static/services/slack.png",
    category=["Customer Success", "Analytics"],
    code_language="hog",
    code="""
let queryRes := fetch(f'{inputs.posthog_host}/api/projects/{project.id}/query/', {
    'method': 'POST',
    'headers': {
        'Authorization': f'Bearer {inputs.posthog_api_key}',
        'Content-Type': 'application/json'
    },
    'body': {
        'query': {
            'kind': 'HogQLQuery',
            'query': inputs.query
        }
    }
});

if (queryRes.status >= 400) {
    throw Error(f'HogQL query failed: {queryRes.status}: {queryRes.body}');
}

let queryResultJson := jsonStringify(queryRes.body.results);
let userMessage := replaceAll(inputs.user_prompt, '{query_result}', queryResultJson);

let llmRes := fetch('https://api.anthropic.com/v1/messages', {
    'method': 'POST',
    'headers': {
        'x-api-key': inputs.anthropic_api_key,
        'anthropic-version': '2023-06-01',
        'Content-Type': 'application/json'
    },
    'body': {
        'model': inputs.anthropic_model,
        'max_tokens': inputs.max_tokens,
        'system': inputs.system_prompt,
        'messages': [{'role': 'user', 'content': userMessage}]
    }
});

if (llmRes.status >= 400) {
    throw Error(f'Anthropic call failed: {llmRes.status}: {llmRes.body}');
}

let summary := llmRes.body.content[1].text;

let slackRes := fetch('https://slack.com/api/chat.postMessage', {
    'method': 'POST',
    'headers': {
        'Authorization': f'Bearer {inputs.slack_workspace.access_token}',
        'Content-Type': 'application/json'
    },
    'body': {
        'channel': inputs.slack_channel,
        'text': summary,
        'blocks': [
            {
                'type': 'section',
                'text': {'type': 'mrkdwn', 'text': summary}
            }
        ]
    }
});

if (slackRes.status != 200 or slackRes.body.ok == false) {
    throw Error(f'Slack post failed: {slackRes.status}: {slackRes.body}');
}
""".strip(),
    inputs_schema=[
        {
            "key": "posthog_host",
            "type": "string",
            "label": "PostHog host",
            "description": "Your PostHog app host. For US Cloud use https://us.posthog.com; for EU use https://eu.posthog.com.",
            "default": "https://us.posthog.com",
            "secret": False,
            "required": True,
        },
        {
            "key": "posthog_api_key",
            "type": "string",
            "label": "PostHog personal API key",
            "description": "A personal API key with the `query:read` scope. Used to run the HogQL query against this project.",
            "secret": True,
            "required": True,
        },
        {
            "key": "query",
            "type": "string",
            "label": "HogQL query",
            "description": "The HogQL query whose results feed into the LLM summary. Aggregate or sample down — the full result set is sent to the model.",
            "secret": False,
            "required": True,
        },
        {
            "key": "anthropic_api_key",
            "type": "string",
            "label": "Anthropic API key",
            "description": "Your Anthropic API key. Stored encrypted; used to call api.anthropic.com on each run.",
            "secret": True,
            "required": True,
        },
        {
            "key": "anthropic_model",
            "type": "string",
            "label": "Anthropic model",
            "description": "Model identifier (e.g. claude-sonnet-4-5, claude-opus-4-5, claude-haiku-4-5).",
            "default": "claude-sonnet-4-5",
            "secret": False,
            "required": True,
        },
        {
            "key": "max_tokens",
            "type": "number",
            "label": "Max output tokens",
            "description": "Upper bound on tokens the model may generate. Slack section blocks render up to ~3000 chars cleanly; 2000 tokens is a safe default.",
            "default": 2000,
            "secret": False,
            "required": True,
        },
        {
            "key": "system_prompt",
            "type": "string",
            "label": "System prompt",
            "description": "Instructions for the model. Describe the role, output format, tone, and what to highlight or omit.",
            "default": "You are a concise product analyst. Read the JSON result of a HogQL query and produce a Slack-ready summary of what the data shows. Lead with the headline number, then 2-4 short bullets on composition or notable changes. Keep it under 200 words. Use Slack mrkdwn (single asterisks for bold, single underscores for italic). No preamble, no meta-commentary.",
            "secret": False,
            "required": True,
        },
        {
            "key": "user_prompt",
            "type": "string",
            "label": "User prompt template",
            "description": "Sent to the model alongside the system prompt. Use the literal placeholder {query_result} to inject the JSON-stringified HogQL results.",
            "default": "Here is the latest data:\n\n{query_result}\n\nWrite the summary.",
            "secret": False,
            "required": True,
        },
        {
            "key": "slack_workspace",
            "type": "integration",
            "integration": "slack",
            "label": "Slack workspace",
            "requiredScopes": "channels:read groups:read chat:write chat:write.customize",
            "secret": False,
            "required": True,
        },
        {
            "key": "slack_channel",
            "type": "integration_field",
            "integration_key": "slack_workspace",
            "integration_field": "slack_channel",
            "label": "Channel to post to",
            "description": "Channel id (e.g. C0123ABC) or #channel-name. The PostHog Slack app must be installed in the workspace and a member of private channels.",
            "secret": False,
            "required": True,
        },
    ],
)
