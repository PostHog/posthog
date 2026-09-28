from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="beta",
    free=True,
    type="destination",
    id="template-pagerduty",
    name="PagerDuty",
    description="Triggers, acknowledges or resolves a PagerDuty incident",
    icon_url="/static/services/pagerduty.png",
    category=["Monitoring & Alerts"],
    code_language="hog",
    code="""
let action := inputs.event_action
if (not has(['trigger', 'acknowledge', 'resolve'], action)) {
    throw Error(f'Unsupported event action "{action}". Use trigger, acknowledge or resolve.')
}

let body := {
    'routing_key': inputs.routing_key,
    'event_action': action
}

if (notEmpty(inputs.dedup_key)) {
    body['dedup_key'] := inputs.dedup_key
}

if (action == 'trigger') {
    let severity := inputs.severity
    if (not has(['critical', 'error', 'warning', 'info'], severity)) {
        severity := 'error'
    }

    let payload := {
        'summary': substring(inputs.summary, 1, 1024),
        'source': inputs.source,
        'severity': severity
    }
    if (notEmpty(inputs.component)) {
        payload['component'] := inputs.component
    }
    if (notEmpty(inputs.event_class)) {
        payload['class'] := inputs.event_class
    }
    if (notEmpty(inputs.custom_details)) {
        payload['custom_details'] := inputs.custom_details
    }

    body['payload'] := payload
    body['client'] := 'PostHog'
    if (notEmpty(inputs.links)) {
        body['links'] := inputs.links
    }
} else if (empty(inputs.dedup_key)) {
    throw Error(f'A dedup key is required to {action} an incident.')
}

let res := fetch('https://events.pagerduty.com/v2/enqueue', {
    'method': 'POST',
    'headers': {
        'Content-Type': 'application/json'
    },
    'body': body
})

if (res.status >= 400) {
    throw Error(f'PagerDuty rejected the event: {res.status}: {res.body}')
}
""".strip(),
    inputs_schema=[
        {
            "key": "routing_key",
            "type": "string",
            "label": "Routing key",
            "description": "The integration key of an Events API v2 integration on your PagerDuty service.",
            "secret": True,
            "required": True,
        },
        {
            "key": "event_action",
            "type": "choice",
            "label": "Event action",
            "description": "Trigger opens an incident. Acknowledge and resolve update the incident with the same dedup key.",
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
            "label": "Dedup key",
            "description": "Events with the same key update one incident. Acknowledge and resolve need it. If you leave it empty, PagerDuty opens a new incident for each trigger.",
            "default": "",
            "secret": False,
            "required": False,
        },
        {
            "key": "summary",
            "type": "string",
            "label": "Summary",
            "description": "The incident title. PagerDuty keeps the first 1024 characters.",
            "default": "{event.event} by {person.name}",
            "secret": False,
            "required": True,
        },
        {
            "key": "source",
            "type": "string",
            "label": "Source",
            "description": "The system that has the problem.",
            "default": "{project.name}",
            "secret": False,
            "required": True,
        },
        {
            "key": "severity",
            "type": "choice",
            "label": "Severity",
            "description": "Any other value is sent as error.",
            "choices": [
                {"label": "Critical", "value": "critical"},
                {"label": "Error", "value": "error"},
                {"label": "Warning", "value": "warning"},
                {"label": "Info", "value": "info"},
            ],
            "default": "error",
            "secret": False,
            "required": True,
        },
        {
            "key": "component",
            "type": "string",
            "label": "Component",
            "description": "The part of the source system that has the problem.",
            "default": "",
            "secret": False,
            "required": False,
        },
        {
            "key": "event_class",
            "type": "string",
            "label": "Class",
            "description": "The type of the event, for example firing.",
            "default": "",
            "secret": False,
            "required": False,
        },
        {
            "key": "custom_details",
            "type": "json",
            "label": "Custom details",
            "description": "Extra data that PagerDuty shows on the incident and can use in event rules.",
            "default": {"event": "{event}", "person": "{person}"},
            "secret": False,
            "required": False,
        },
        {
            "key": "links",
            "type": "json",
            "label": "Links",
            "description": "A list of links with href and text that PagerDuty shows on the incident.",
            "default": [{"href": "{event.url}", "text": "View event in PostHog"}],
            "secret": False,
            "required": False,
        },
    ],
)
