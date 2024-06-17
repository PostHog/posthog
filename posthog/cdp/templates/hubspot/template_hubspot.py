from posthog.cdp.templates.hog_function_template import HogFunctionTemplate


template: HogFunctionTemplate = HogFunctionTemplate(
    status="alpha",
    id="template-hubspot",
    name="Create Hubspot contact",
    description="Creates a new contact in Hubspot whenever an event is triggered.",
    icon_url="/api/projects/@current/hog_functions/icon/?id=hubspot.com",
    hog="""
let properties := inputs.properties
properties.email := inputs.email

if (empty(properties.email)) {
    print('`email` input is empty. Not creating a contact.')
    return
}

let body := {
    'properties': properties
}

let headers := {
    'Authorization': f'Bearer {inputs.access_token}',
    'Content-Type': 'application/json'
}

let res := fetch('https://api.hubapi.com/crm/v3/objects/contacts', {
  'method': 'POST',
  'headers': headers,
  'body': body
})

if (res.status == 409) {
    let existingId := replaceOne(res.body.message, 'Contact already exists. Existing ID: ', '')
    let updateRes := fetch(f'https://api.hubapi.com/crm/v3/objects/contacts/{existingId}', {
        'method': 'PATCH',
        'headers': headers,
        'body': body
    })

    if (updateRes.status != 200 or updateRes.body.status == 'error') {
        print('Error updating contact:', updateRes.body)
        return
    }
    print('Contact updated successfully!')
    return
} else if (res.status != 200 or res.body.status == 'error') {
    print('Error creating contact:', res.body)
    return
} else {
    print('Contact created successfully!')
}


""".strip(),
    inputs_schema=[
        {
            "key": "access_token",
            "type": "string",
            "label": "Access token",
            "description": "Can be acquired under Profile Preferences -> Integrations -> Private Apps",
            "secret": True,
            "required": True,
        },
        {
            "key": "email",
            "type": "string",
            "label": "Email of the user",
            "description": "Where to find the email for the contact to be created. You can use the filters section to filter out unwanted emails or internal users.",
            "default": "{person.properties.email}",
            "secret": False,
            "required": True,
        },
        {
            "key": "properties",
            "type": "dictionary",
            "label": "Property mapping",
            "description": "Map any event properties to Hubspot properties.",
            "default": {
                "name": "{person.properties.name}",
                "company": "{person.properties.company}",
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
