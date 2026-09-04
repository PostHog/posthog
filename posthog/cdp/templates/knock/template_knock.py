from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="beta",
    free=False,
    type="destination",
    id="template-knock",
    name="Knock",
    description="Send events to Knock",
    icon_url="/static/services/knock.png",
    category=["SMS & Push Notifications"],
    filters={
        "events": [
            {"id": "$identify", "name": "$identify", "type": "events", "order": 0},
            {"id": "$pageview", "name": "$pageview", "type": "events", "order": 1},
        ],
        "actions": [],
        "filter_test_accounts": True,
    },
    code_language="hog",
    code="""
if (empty(inputs.userId)) {
    print('No User ID set. Skipping...')
    return
}

let body := {
    'type': 'track',
    'event': event.event,
    'userId': inputs.userId,
    'properties': inputs.include_all_properties ? event.properties : {},
    'messageId': event.uuid,
    'timestamp': event.timestamp
}
if (inputs.include_all_properties and not empty(event.elements_chain)) {
    body['properties']['$elements_chain'] := event.elements_chain
}

for (let key, value in inputs.attributes) {
    if (not empty(value)) {
        body['properties'][key] := value
    }
}

let res := fetch(inputs.webhookUrl, {
    'method': 'POST',
    'headers': {
        'Content-Type': 'application/json'
    },
    'body': body
})

if (res.status >= 400) {
    throw Error(f'Error from knock.app (status {res.status}): {res.body}')
}

""".strip(),
    inputs_schema=[
        {
            "key": "webhookUrl",
            "type": "string",
            "label": "Knock.app webhook destination URL",
            "secret": False,
            "required": True,
        },
        {
            "key": "userId",
            "type": "string",
            "label": "User ID",
            "description": "The identifier for the user in Knock. The default sends the PostHog distinct ID, which matches the identifier your app already uses. It sends nothing for an anonymous event, where the distinct ID is still the device ID, and nothing for an event with no person, so you do not get Knock recipients you cannot notify. Set this to another value, such as an `email` or your own `id`, if your Knock users use a different identifier. Do not use the PostHog person ID (`{person.id}`): it is a PostHog-owned UUID that Knock has never seen, so it creates a second Knock user record. If the value is empty, nothing is sent. See here for more information: https://docs.knock.app/concepts/users#user-identifiers",
            "default": "{not empty(person.id) and event.distinct_id != event.properties.$device_id ? event.distinct_id : null}",
            "secret": False,
            "required": True,
        },
        {
            "key": "include_all_properties",
            "type": "boolean",
            "label": "Include all properties as attributes",
            "description": "If set, all event properties will be included as attributes. Individual attributes can be overridden below.",
            "default": False,
            "secret": False,
            "required": True,
        },
        {
            "key": "attributes",
            "type": "dictionary",
            "label": "Attribute mapping",
            "description": "Map of Knock.app attributes and their values. You can use the filters section to filter out unwanted events.",
            "default": {
                "email": "{person.properties.email}",
                "name": "{person.properties.name}",
            },
            "secret": False,
            "required": False,
        },
    ],
)
