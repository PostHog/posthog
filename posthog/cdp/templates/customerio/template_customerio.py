from posthog.cdp.templates.hog_function_template import HogFunctionTemplate

# Based off of https://customer.io/docs/api/track/#operation/entity

template: HogFunctionTemplate = HogFunctionTemplate(
    status="alpha",
    id="template-customerio",
    name="Identify customers in Customer.io",
    description="Syncs persons with Customer.io",
    icon_url="/static/services/customerio.png",
    hog="""
let res := fetch(f'https://{inputs.host}/api/v2/entity', {
    'method': 'POST',
    'headers': {
        'User-Agent': 'PostHog Customer.io App',
        'Authorization': f'Basic {base64Encode(f'{inputs.site_id}:{inputs.token}')}',
        'Content-Type': 'application/json'
    },
    'body': {
        'type': 'person',
        'action': 'identify',
        'identifiers': inputs.identifiers,
        'attributes': inputs.properties
    }
})

if (res.status >= 400) {
    print('Error from customer.io api:', res.status, res.body)
}

""".strip(),
    inputs_schema=[
        {
            "key": "site_id",
            "type": "string",
            "label": "Customer.io site ID",
            "secret": False,
            "required": True,
        },
        {
            "key": "token",
            "type": "string",
            "label": "Customer.io API Key",
            "description": "You can find your API key in your Customer.io account settings (https://fly.customer.io/settings/api_credentials)",
            "secret": True,
            "required": True,
        },
        {
            "key": "host",
            "type": "choice",
            "choices": [
                {
                    "label": "US (track.customer.io)",
                    "value": "track.customer.io",
                },
                {
                    "label": "EU (track-eu.customer.io)",
                    "value": "track-eu.customer.io",
                },
            ],
            "label": "Customer.io region",
            "description": "Use the EU variant if your Customer.io account is based in the EU region",
            "default": "track.customer.io",
            "secret": False,
            "required": True,
        },
        {
            "key": "identifiers",
            "type": "dictionary",
            "label": "Identifiers",
            "description": "You can choose to fill this from an `email` property or an `id` property. If the value is empty nothing will be sent. See here for more information: https://customer.io/docs/api/track/#operation/entity",
            "default": {
                "email": "{person.properties.email}",
            },
            "secret": False,
            "required": True,
        },
        {
            "key": "properties",
            "type": "dictionary",
            "label": "Attribute mapping",
            "description": "Map of Customer.io attributes and their values. You can use the filters section to filter out unwanted events.",
            "default": {
                "email": "{person.properties.email}",
                "lastname": "{person.properties.lastname}",
                "firstname": "{person.properties.firstname}",
            },
            "secret": False,
            "required": True,
        },
    ],
    filters={
        "events": [{"id": "$identify", "name": "$identify", "type": "events", "order": 0}],
        "actions": [],
        "filter_test_accounts": True,
    },
)
