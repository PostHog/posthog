from posthog.cdp.templates.hog_function_template import HogFunctionTemplate


template: HogFunctionTemplate = HogFunctionTemplate(
    status="alpha",
    id="template-customerio",
    name="Update persons in Customer.io",
    description="Updates persons in Customer.io",
    icon_url="/api/projects/@current/hog_functions/icon/?id=customer.io",
    hog="""
fn callCustomerIoApi(method, path, body) {
    // TODO: Base64 encode the site_id and token
    let response := fetch(f'https://{inputs.host}{path}', {
      'headers': {
        'User-Agent': 'PostHog Customer.io App',
        'Authorization': f'Basic {inputs.site_id}:{inputs.token}',
        'Content-Type': 'application/json'
      },
      'body': body,
    })

    if (response.status >= 400) {
        print('Error calling Customer.io API:', response)
    }
}

fn trackIdentify() {
    // Upsert the customer
    let payload := {
        'type': 'person',
        'identifiers': {
            // TODO: Make the id input configurable
        'id': inputs.identifier'
        },
        'action': 'identify',
        'attributes': inputs.properties
    }

    await callCustomerIoApi('POST', f'/api/v2/entity', payload)
}

trackIdentify()

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
            "key": "identifier",
            "type": "string",
            "label": "The ID that should be used for the user",
            "description": "You can choose to fill this from an email property or an ID property. If the value is empty nothing will be sent.",
            "default": "{person.properties.email}",
            "secret": False,
            "required": True,
        },
        {
            "key": "host",
            "type": "choice",
            "choices": ["track.customer.io", "track-eu.customer.io"],
            "label": "Tracking endpoint",
            "description": "Use the EU variant if your Customer.io account is based in the EU region",
            "default": "track.customer.io",
            "secret": False,
            "required": True,
        },
        {
            "key": "properties",
            "type": "dictionary",
            "label": "Property mapping",
            "description": "Map any event properties to Hubspot properties.",
            "default": {
                "company": "{person.properties.company}",
                "lastname": "{person.properties.lastname}",
                "firstname": "{person.properties.firstname}",
                "phone": "{person.properties.phone}",
                "website": "{person.properties.website}",
                "domain": "{person.properties.website}",
                "company_website": "{person.properties.website}",
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
