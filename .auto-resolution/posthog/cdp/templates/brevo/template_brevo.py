from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="stable",
    free=False,
    type="destination",
    id="template-brevo",
    name="Brevo",
    description="Update contacts in Brevo",
    icon_url="/static/services/brevo.png",
    category=["Email Marketing"],
    code_language="hog",
    code="""
if (empty(inputs.email)) {
    print('No email set. Skipping...')
    return
}

let body := {
    'email': inputs.email,
    'updateEnabled': true,
    'attributes': {}
}

for (let key, value in inputs.attributes) {
    if (not empty(value)) {
        body.attributes[key] := value
    }
}

let res := fetch(f'https://api.brevo.com/v3/contacts', {
    'method': 'POST',
    'headers': {
        'api-key': inputs.apiKey,
        'Content-Type': 'application/json',
    },
    'body': body
})
if (res.status >= 400) {
    throw Error(f'Error from api.brevo.com (status {res.status}): {res.body}')
}
""".strip(),
    inputs_schema=[
        {
            "key": "apiKey",
            "type": "string",
            "label": "Brevo API Key",
            "description": "Check out this page on how to get your API key: https://help.brevo.com/hc/en-us/articles/209467485-Create-and-manage-your-API-keys",
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
            "key": "attributes",
            "type": "dictionary",
            "label": "Attributes",
            "description": "For information on potential attributes, refer to the following page: https://help.brevo.com/hc/en-us/articles/10617359589906-Create-and-manage-contact-attributes",
            "default": {
                "EMAIL": "{person.properties.email}",
                "FIRSTNAME": "{person.properties.firstname}",
                "LASTNAME": "{person.properties.lastname}",
            },
            "secret": False,
            "required": True,
        },
    ],
    filters={
        "events": [
            {"id": "$identify", "name": "$identify", "type": "events", "order": 0},
            {"id": "$set", "name": "$set", "type": "events", "order": 0},
        ],
        "actions": [],
        "filter_test_accounts": True,
    },
)
