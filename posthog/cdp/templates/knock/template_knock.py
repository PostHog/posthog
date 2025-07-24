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
            "description": "You can choose to fill this from an `email` property or an `id` property. If the value is empty nothing will be sent. See here for more information: https://docs.gleap.io/server/rest-api",
            "default": "{person.id}",
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
                "price": "{event.properties.price}",
            },
            "secret": False,
            "required": False,
        },
    ],
)
