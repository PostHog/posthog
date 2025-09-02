import dataclasses
from copy import deepcopy

from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC, HogFunctionTemplateMigrator

template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="stable",
    free=False,
    type="destination",
    id="template-loops",
    name="Loops",
    description="Update contacts in Loops.so",
    icon_url="/static/services/loops.png",
    category=["Email Marketing"],
    code_language="hog",
    code="""
if (empty(inputs.email)) {
    print('No email set. Skipping...')
    return
}

let payload := {
    'email': inputs.email,
    'userId': person.id,
}

if (inputs.include_all_properties) {
    for (let key, value in person.properties) {
        if (not empty(value) and not key like '$%') {
            payload[key] := value
        }
    }
}

for (let key, value in inputs.properties) {
    if (not empty(value)) {
        payload[key] := value
    }
}

let res := fetch('https://app.loops.so/api/v1/contacts/update', {
    'method': 'POST',
    'headers': {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {inputs.apiKey}',
    },
    'body': payload
})

if (res.status >= 400) {
    throw Error(f'Error from app.loops.so (status {res.status}): {res.body}')
}
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
        },
        {
            "key": "email",
            "type": "string",
            "label": "Email of the user",
            "description": "Where to find the email of the user.",
            "default": "{person.properties.email}",
            "secret": False,
            "required": True,
        },
        {
            "key": "include_all_properties",
            "type": "boolean",
            "label": "Include all properties as attributes",
            "description": "If set, all person properties will be included. Individual attributes can be overridden below.",
            "default": False,
            "secret": False,
            "required": True,
        },
        {
            "key": "properties",
            "type": "dictionary",
            "label": "Property mapping",
            "description": "Map of Loops.so properties and their values. You can use the filters section to filter out unwanted events.",
            "default": {
                "firstName": "{person.properties.firstname}",
                "lastName": "{person.properties.lastname}",
            },
            "secret": False,
            "required": False,
        },
    ],
    filters={
        "events": [
            {"id": "$identify", "name": "$identify", "type": "events", "order": 0},
            {"id": "$set", "name": "$set", "type": "events", "order": 1},
        ],
        "actions": [],
        "filter_test_accounts": True,
    },
)

template_send_event: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="stable",
    free=False,
    type="destination",
    id="template-loops-event",
    name="Loops",
    description="Send events to Loops.so",
    icon_url="/static/services/loops.png",
    category=["Email Marketing"],
    code_language="hog",
    code="""
if (empty(inputs.email)) {
    print('No email set. Skipping...')
    return
}

let payload := {
    'email': inputs.email,
    'userId': person.id,
    'eventName': event.event,
    'eventProperties': {}
}

if (inputs.include_all_properties) {
    for (let key, value in event.properties) {
        if (not empty(value) and not key like '$%') {
            payload.eventProperties[key] := value
        }
    }
}

for (let key, value in inputs.properties) {
    if (not empty(value)) {
        payload.eventProperties[key] := value
    }
}

let res := fetch('https://app.loops.so/api/v1/events/send', {
    'method': 'POST',
    'headers': {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {inputs.apiKey}',
    },
    'body': payload
})

if (res.status >= 400) {
    throw Error(f'Error from app.loops.so (status {res.status}): {res.body}')
}
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
        },
        {
            "key": "email",
            "type": "string",
            "label": "Email of the user",
            "description": "Where to find the email of the user.",
            "default": "{person.properties.email}",
            "secret": False,
            "required": True,
        },
        {
            "key": "include_all_properties",
            "type": "boolean",
            "label": "Include all properties as attributes",
            "description": "If set, all event properties will be included. Individual attributes can be overridden below.",
            "default": False,
            "secret": False,
            "required": True,
        },
        {
            "key": "properties",
            "type": "dictionary",
            "label": "Property mapping",
            "description": "Map of Loops.so properties and their values. You can use the filters section to filter out unwanted events.",
            "default": {
                "pathname": "{event.properties.$pathname}",
            },
            "secret": False,
            "required": False,
        },
    ],
    filters={
        "events": [
            {"id": "$pageview", "name": "$pageview", "type": "events", "order": 0},
        ],
        "actions": [],
        "filter_test_accounts": True,
    },
)


class TemplateLoopsMigrator(HogFunctionTemplateMigrator):
    plugin_url = "https://github.com/PostHog/posthog-loops-plugin"

    @classmethod
    def migrate(cls, obj):
        hf = deepcopy(dataclasses.asdict(template))
        hf["hog"] = hf["code"]
        del hf["code"]

        apiKey = obj.config.get("apiKey", "")
        trackedEvents = obj.config.get("trackedEvents", "")
        shouldTrackIdentify = obj.config.get("shouldTrackIdentify", "yes")

        hf["filters"] = {}
        hf["filters"]["events"] = []

        events_to_filter = [event.strip() for event in trackedEvents.split(",") if event.strip()]

        if events_to_filter:
            hf["filters"]["events"] = [
                {"id": event, "name": event, "type": "events", "order": 0} for event in events_to_filter
            ]

        if shouldTrackIdentify == "yes" and len(hf["filters"]["events"]) >= 1:
            hf["filters"]["events"].append({"id": "$identify", "name": "$identify", "type": "events", "order": 0})
            hf["filters"]["events"].append({"id": "$set", "name": "$set", "type": "events", "order": 1})

        hf["inputs"] = {
            "apiKey": {"value": apiKey},
        }

        return hf
