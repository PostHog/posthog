from posthog.cdp.templates.hog_function_template import HogFunctionTemplate

# Based off of https://www.twilio.com/docs/sendgrid/api-reference/contacts/add-or-update-a-contact

template: HogFunctionTemplate = HogFunctionTemplate(
    status="beta",
    id="template-sendgrid",
    name="Update marketing contacts in Sendgrid",
    description="Update marketing contacts in Sendgrid",
    icon_url="/static/services/sendgrid.png",
    hog="""
let email := inputs.email

if (empty(email)) {
    print('`email` input is empty. Not updating contacts.')
    return
}

let contact := {
  'email': email,
}

for (let key, value in inputs.properties) {
    if (not empty(value)) {
        contact[key] := value
    }
}

let res := fetch('https://api.sendgrid.com/v3/marketing/contacts', {
    'method': 'PUT',
    'headers': {
        'Authorization': f'Bearer {inputs.api_key}',
        'Content-Type': 'application/json'
    },
    'body': {
      'contacts': [contact]
    }
})

if (res.status > 300) {
    print('Error updating contact:', res.status, res.body)
}
""".strip(),
    inputs_schema=[
        {
            "key": "api_key",
            "type": "string",
            "label": "Sendgrid API Key",
            "description": "See https://app.sendgrid.com/settings/api_keys",
            "secret": True,
            "required": True,
        },
        {
            "key": "email",
            "type": "string",
            "label": "The email of the user",
            "default": "{person.properties.email}",
            "secret": False,
            "required": True,
        },
        {
            "key": "properties",
            "type": "dictionary",
            "label": "Property mapping",
            "description": "Map of reserved properties (https://www.twilio.com/docs/sendgrid/api-reference/contacts/add-or-update-a-contact)",
            "default": {
                "last_name": "{person.properties.last_name}",
                "first_name": "{person.properties.first_name}",
                "city": "{person.properties.city}",
                "country": "{person.properties.country}",
                "postal_code": "{person.properties.postal_code}",
            },
            "secret": False,
            "required": True,
        },
        # TODO: Add dynamic code for loading custom fields
    ],
    filters={
        "events": [{"id": "$identify", "name": "$identify", "type": "events", "order": 0}],
        "actions": [],
        "filter_test_accounts": True,
    },
)
