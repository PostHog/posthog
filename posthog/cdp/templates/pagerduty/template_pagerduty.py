from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="stable",
    free=True,
    type="destination",
    id="template-pagerduty",
    name="PagerDuty",
    description="Sends an event to the PagerDuty Events API v2 to trigger, acknowledge or resolve an incident",
    icon_url="/static/services/pagerduty.png",
    category=["Monitoring & Alerts"],
    code_language="hog",
    code="""
let endpoint := 'https://events.pagerduty.com/v2/enqueue'
if (inputs.region == 'eu') {
    endpoint := 'https://events.eu.pagerduty.com/v2/enqueue'
}

let payload := {
    'summary': inputs.summary,
    'source': inputs.source,
    'severity': inputs.severity
}
if (not empty(inputs.custom_details)) {
    payload['custom_details'] := inputs.custom_details
}

let body := {
    'routing_key': inputs.routing_key,
    'event_action': inputs.event_action,
    'payload': payload,
    'client': 'PostHog'
}
if (not empty(inputs.dedup_key)) {
    body['dedup_key'] := inputs.dedup_key
}
if (not empty(inputs.links)) {
    body['links'] := inputs.links
}
if (not empty(inputs.client_url)) {
    body['client_url'] := inputs.client_url
}

let res := fetch(endpoint, {
    'method': 'POST',
    'headers': {
        'Content-Type': 'application/json'
    },
    'body': body
});

if (res.status >= 400) {
    throw Error(f'Failed to send event to PagerDuty: {res.status}: {res.body}');
}
""".strip(),
    inputs_schema=[
        {
            "key": "routing_key",
            "type": "string",
            "label": "Integration key",
            "description": "The 32-character integration key of an Events API v2 integration on the PagerDuty service to notify.",
            "secret": True,
            "required": True,
        },
        {
            "key": "region",
            "type": "choice",
            "label": "Service region",
            "description": "The PagerDuty service region of your account.",
            "choices": [
                {"label": "US", "value": "us"},
                {"label": "EU", "value": "eu"},
            ],
            "default": "us",
            "secret": False,
            "required": True,
        },
        {
            "key": "event_action",
            "type": "choice",
            "label": "Event action",
            "description": "Trigger opens an incident. Acknowledge and resolve act on the incident that has the same deduplication key.",
            "choices": [
                {"label": "Trigger", "value": "trigger"},
                {"label": "Acknowledge", "value": "acknowledge"},
                {"label": "Resolve", "value": "resolve"},
            ],
            "default": "trigger",
            "secret": False,
            "required": True,
        },
        {
            "key": "dedup_key",
            "type": "string",
            "label": "Deduplication key",
            "description": "Events with the same key belong to the same incident, so a resolve event closes the incident that a trigger event opened. Leave empty to let PagerDuty create a new incident for each event.",
            "default": "",
            "secret": False,
            "required": False,
        },
        {
            "key": "summary",
            "type": "string",
            "label": "Summary",
            "description": "A short description of the problem. PagerDuty shows it as the incident title.",
            "default": "{event.event} by {person.name}",
            "secret": False,
            "required": True,
        },
        {
            "key": "source",
            "type": "string",
            "label": "Source",
            "description": "The system the event comes from, for example a service name or hostname.",
            "default": "PostHog",
            "secret": False,
            "required": True,
        },
        {
            "key": "severity",
            "type": "choice",
            "label": "Severity",
            "description": "The severity PagerDuty records on the alert. Your service settings decide how each severity notifies.",
            "choices": [
                {"label": "Critical", "value": "critical"},
                {"label": "Error", "value": "error"},
                {"label": "Warning", "value": "warning"},
                {"label": "Info", "value": "info"},
            ],
            "default": "critical",
            "secret": False,
            "required": True,
        },
        {
            "key": "custom_details",
            "type": "json",
            "label": "Custom details",
            "description": "Extra fields PagerDuty shows on the alert.",
            "default": {"event": "{event}", "person": "{person}"},
            "secret": False,
            "required": False,
        },
        {
            "key": "links",
            "type": "json",
            "label": "Links",
            "description": "Links PagerDuty attaches to the alert, as a list of objects with href and text.",
            "default": [],
            "secret": False,
            "required": False,
        },
        {
            "key": "client_url",
            "type": "string",
            "label": "Client URL",
            "description": "Where the PostHog link on the incident points to.",
            "default": "{project.url}",
            "secret": False,
            "required": False,
        },
    ],
)
