from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="stable",
    free=False,
    type="destination",
    id="template-klime",
    name="Klime",
    description="Send events to Klime",
    icon_url="/static/services/klime.png",
    category=["Analytics"],
    code_language="hog",
    code="""
let action := inputs.action

if (action == 'automatic') {
    if (event.event in ('$identify', '$set')) {
        action := 'identify'
    } else if (event.event == '$group_identify') {
        action := 'group'
    } else {
        action := 'track'
    }
}

let payload := {
    'type': action,
    'messageId': event.uuid,
    'timestamp': event.timestamp
}

if (not empty(inputs.userId)) {
    payload['userId'] := inputs.userId
}

if (action == 'track') {
    payload['event'] := event.event
    if (not empty(inputs.groupId)) {
        payload['groupId'] := inputs.groupId
    }
    let props := {}
    if (inputs.include_all_properties) {
        for (let key, value in event.properties) {
            if (not key like '$%') {
                props[key] := value
            }
        }
    }
    for (let key, value in inputs.properties) {
        if (not empty(value)) {
            props[key] := value
        }
    }
    if (not empty(props)) {
        payload['properties'] := props
    }
} else if (action == 'identify') {
    if (empty(inputs.userId)) {
        print('No user ID set. Skipping as user ID is required for identify events.')
        return
    }
    let traits := {}
    if (inputs.include_all_properties) {
        for (let key, value in person.properties) {
            if (not key like '$%') {
                traits[key] := value
            }
        }
    }
    for (let key, value in inputs.properties) {
        if (not empty(value)) {
            traits[key] := value
        }
    }
    if (not empty(traits)) {
        payload['traits'] := traits
    }
} else if (action == 'group') {
    if (empty(inputs.groupId)) {
        print('No group ID set. Skipping as group ID is required for group events.')
        return
    }
    payload['groupId'] := inputs.groupId
    let traits := {}
    for (let key, value in inputs.properties) {
        if (not empty(value)) {
            traits[key] := value
        }
    }
    if (not empty(traits)) {
        payload['traits'] := traits
    }
}

payload['context'] := {
    'library': {
        'name': 'posthog-cdp',
        'version': '1.0.0'
    }
}

let res := fetch('https://i.klime.com/v1/batch', {
    'method': 'POST',
    'headers': {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {inputs.writeKey}'
    },
    'body': {
        'batch': [payload]
    }
})

if (res.status >= 400) {
    throw Error(f'Error from Klime API: {res.status}: {res.body}')
}""",
    inputs_schema=[
        {
            "key": "writeKey",
            "type": "string",
            "label": "Klime Write Key",
            "description": "Your Klime write key for authentication. Find it in your Klime dashboard.",
            "default": "",
            "secret": True,
            "required": True,
        },
        {
            "key": "action",
            "type": "choice",
            "label": "Action",
            "description": "How to map PostHog events to Klime event types. Automatic converts $identify/$set to identify, $group_identify to group, and everything else to track.",
            "default": "automatic",
            "choices": [
                {"label": "Automatic", "value": "automatic"},
                {"label": "Track", "value": "track"},
                {"label": "Identify", "value": "identify"},
                {"label": "Group", "value": "group"},
            ],
            "secret": False,
            "required": True,
        },
        {
            "key": "userId",
            "type": "string",
            "label": "User ID",
            "description": "User identifier to send to Klime. Required for identify events.",
            "default": "{event.distinct_id}",
            "secret": False,
            "required": False,
        },
        {
            "key": "groupId",
            "type": "string",
            "label": "Group ID",
            "description": "Organization or account identifier. Required for group events.",
            "default": "",
            "secret": False,
            "required": False,
        },
        {
            "key": "include_all_properties",
            "type": "boolean",
            "label": "Include all properties",
            "description": "If set, all event properties (for track) or person properties (for identify) will be included. Individual properties can be overridden below.",
            "default": False,
            "secret": False,
            "required": True,
        },
        {
            "key": "properties",
            "type": "dictionary",
            "label": "Property mapping",
            "description": "Map of property names to values. These are sent as properties (track) or traits (identify/group).",
            "default": {},
            "secret": False,
            "required": False,
        },
    ],
    filters={
        "events": [
            {"id": "$identify", "name": "$identify", "type": "events", "order": 0},
            {"id": "$pageview", "name": "$pageview", "type": "events", "order": 0},
        ],
        "actions": [],
        "filter_test_accounts": True,
    },
)
