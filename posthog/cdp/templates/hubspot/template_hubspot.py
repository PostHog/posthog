from posthog.cdp.templates.hog_function_template import HogFunctionTemplate


template: HogFunctionTemplate = HogFunctionTemplate(
    status="alpha",
    id="template-hubspot",
    name="Create Hubspot contact",
    description="Creates a new contact in Hubspot whenever an event is triggered.",
    icon_url="/api/projects/@current/hog_functions/icon/?id=hubspot.com",
    hog="""
let props := inputs.properties
let email := inputs.email

if (email == null or email == '') {
    print('ERROR - Email not found!')
    return
}

let fetchPayload := {
  'method': 'POST',
  'headers': {
    'Authorization': f'Bearer {inputs.access_token}',
    'Content-Type': 'application/json'
  },
  'body': { 'properties': props }
}

print(props, fetchPayload)


let addContactResponse := fetch('https://api.hubapi.com/crm/v3/objects/contacts', fetchPayload)

print(addContactResponse)
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
