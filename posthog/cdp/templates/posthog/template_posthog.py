from posthog.cdp.templates.hog_function_template import HogFunctionTemplate


template: HogFunctionTemplate = HogFunctionTemplate(
    status="beta",
    id="template-posthog-replicator",
    name="Replicate data to another PostHog instance",
    description="Send a copy of the incoming data in realtime to another PostHog instance",
    icon_url="/static/posthog-icon.svg",
    hog="""
let host := inputs.host
let token := inputs.token
let include_all_properties := inputs.include_all_properties
let propertyOverrides := inputs.properties
let properties := include_all_properties ? event.properties : {}

for (let key, value in propertyOverrides) {
    properties[key] := value
}

fetch(f'{host}/e', {
    'method': 'POST',
    'headers': {
        'Content-Type': 'application/json'
    },
    'body': {
        'token': token,
        'event': event.name,
        'timestamp': event.timestamp,
        'distinct_id': event.distinct_id,
        'properties': properties
    }
})
""".strip(),
    inputs_schema=[
        {
            "key": "host",
            "type": "string",
            "label": "PostHog host",
            "description": "For cloud accounts this is either https://us.i.posthog.com or https://eu.i.posthog.com",
            "default": "https://us.posthog.com",
            "secret": False,
            "required": True,
        },
        {
            "key": "token",
            "type": "string",
            "label": "PostHog API key",
            "secret": False,
            "required": True,
        },
        {
            "key": "include_all_properties",
            "type": "boolean",
            "label": "Include all properties by default",
            "description": "If set, all event properties will be included in the payload. Individual properties can be overridden below.",
            "default": True,
            "secret": False,
            "required": True,
        },
        {
            "key": "properties",
            "type": "dictionary",
            "label": "Property overrides",
            "description": "Provided values will override the event properties.",
            "default": {},
            "secret": False,
            "required": False,
        },
    ],
)
