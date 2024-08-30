from posthog.cdp.templates.hog_function_template import HogFunctionTemplate


template: HogFunctionTemplate = HogFunctionTemplate(
    status="beta",
    id="template-loops",
    name="Send events to Loops",
    description="Passes PostHog events to Loops.so",
    icon_url="/static/services/loops.png",
    hog="""
let apiKey := inputs.apiKey

let payload := {
    'userId': event.distinct_id,
    'eventName': event.name == '$set' ? '$identify' : event.name,
    'email': person.properties.email
}
for (let key, value in person.properties) {
    payload[key] := value
}
fetch('https://app.loops.so/api/v1/events/send', {
    'method': 'POST',
    'headers': {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {apiKey}',
    },
    'body': payload
})
""".strip(),
    inputs_schema=[
        {
            "key": "apiKey",
            "type": "string",
            "label": "Loops API Key",
            "description": "Loops API Key",
            "default": "",
            "secret": True,
            "required": True,
        }
    ],
)
