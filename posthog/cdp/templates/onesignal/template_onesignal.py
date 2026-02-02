from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="beta",
    free=False,
    type="destination",
    id="template-onesignal",
    name="OneSignal",
    description="Send events to OneSignal",
    icon_url="/static/services/onesignal.svg",
    category=["Marketing"],
    code_language="hog",
    code="""
let properties := inputs.eventProperties
if (empty(properties)) {
  properties := event.properties
}

let getPayload := () -> {
  'external_id': inputs.externalId,
  'name': inputs.eventName,
  'properties': properties,
  'timestamp': inputs.eventTimestamp
}

let payload := getPayload()

let res := fetch(f'https://api.onesignal.com/apps/{inputs.appId}/custom_events', {
  'method': 'POST',
  'headers': {
    'Authorization': f'Key {inputs.apiKey}',
    'Content-Type': 'application/json',
    'OneSignal-Usage': 'PostHog | Partner Integration'
  },
  'body': {'events':[payload]}
})

if (res.status >= 200 and res.status < 300) {
  print(f'Event sent successfully! Response: {res.status} {res.body}')
} else {
  throw Error(f'Error sending event: {res.status} {res.body}')
}
""".strip(),
    inputs_schema=[
        {
            "key": "appId",
            "type": "string",
            "label": "OneSignal App ID",
            "description": "Your OneSignal App ID. You can find this in your OneSignal dashboard under Settings > Keys & IDs.",
            "default": "",
            "secret": False,
            "required": True,
        },
        {
            "key": "apiKey",
            "type": "string",
            "label": "OneSignal REST API Key",
            "description": "Your OneSignal REST API Key. You can find this in your OneSignal dashboard under Settings > Keys & IDs.",
            "default": "",
            "secret": True,
            "required": True,
        },
        {
            "key": "externalId",
            "type": "string",
            "label": "External ID",
            "description": "A unique identifier that is used to identify this person across OneSignal, PostHog, and other external systems.",
            "default": "{person.id}",
            "secret": False,
            "required": True,
        },
        {
            "key": "eventName",
            "type": "string",
            "label": "Event name",
            "description": "The name of the event to send to OneSignal.",
            "default": "{event.event}",
            "secret": False,
            "required": True,
        },
        {
            "key": "eventProperties",
            "type": "json",
            "label": "Event properties",
            "description": "Additional properties to include with the event. Leave empty to use all event properties, or specify custom properties.",
            "default": {},
            "secret": False,
            "required": False,
        },
        {
            "key": "eventTimestamp",
            "type": "string",
            "label": "Event timestamp",
            "description": "The timestamp of the event.",
            "default": "{event.timestamp}",
            "secret": False,
            "required": True,
        },
    ],
)
