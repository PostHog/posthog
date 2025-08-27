from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="beta",
    free=False,
    type="destination",
    id="template-activecampaign",
    name="ActiveCampaign",
    description="Creates a new contact in ActiveCampaign whenever an event is triggered.",
    icon_url="/static/services/activecampaign.png",
    category=["Email Marketing"],
    code_language="hog",
    code="""
if (empty(inputs.email)) {
    print('`email` input is empty. Not creating a contact.')
    return
}

let contact := {
    'email': inputs.email,
    'fieldValues': [],
}

if (not empty(inputs.firstName)) contact.firstName := inputs.firstName
if (not empty(inputs.lastName)) contact.lastName := inputs.lastName
if (not empty(inputs.phone)) contact.phone := inputs.phone

for (let key, value in inputs.attributes) {
    if (not empty(value)) {
        contact.fieldValues := arrayPushBack(contact.fieldValues, {'field': key, 'value': value})
    }
}

let res := fetch(f'https://{inputs.accountName}.api-us1.com/api/3/contact/sync', {
    'method': 'POST',
    'headers': {
        'content-type': 'application/json',
        'Api-Token': inputs.apiKey
    },
    'body': {
        'contact': contact
    }
})

if (res.status >= 400) {
    throw Error(f'Error from {inputs.accountName}.api-us1.com (status {res.status}): {res.body}')
} else {
    print('Contact has been created or updated successfully!')
}
""".strip(),
    inputs_schema=[
        {
            "key": "accountName",
            "type": "string",
            "label": "Account name",
            "description": "Usually in the form of <accountName>.activehosted.com. You can use this page to figure our your account name: https://www.activecampaign.com/login/lookup.php",
            "default": "",
            "secret": False,
            "required": True,
        },
        {
            "key": "apiKey",
            "type": "string",
            "label": "Your ActiveCampaign API Key",
            "description": "See the docs here: https://help.activecampaign.com/hc/en-us/articles/207317590-Getting-started-with-the-API#h_01HJ6REM2YQW19KYPB189726ST",
            "default": "",
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
            "key": "firstName",
            "type": "string",
            "label": "First name of the user",
            "description": "Where to find the first name for the contact to be created.",
            "default": "{person.properties.firstName}",
            "secret": False,
            "required": True,
        },
        {
            "key": "lastName",
            "type": "string",
            "label": "Last name of the user",
            "description": "Where to find the last name for the contact to be created.",
            "default": "{person.properties.lastName}",
            "secret": False,
            "required": True,
        },
        {
            "key": "phone",
            "type": "string",
            "label": "Phone number of the user",
            "description": "Where to find the phone number for the contact to be created.",
            "default": "{person.properties.phone}",
            "secret": False,
            "required": True,
        },
        {
            "key": "attributes",
            "type": "dictionary",
            "label": "Additional person fields",
            "description": "Map any values to ActiveCampaign person fields. (fieldId:value)",
            "default": {
                "1": "{person.properties.company}",
                "2": "{person.properties.website}",
            },
            "secret": False,
            "required": True,
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
