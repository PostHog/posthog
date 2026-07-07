from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

# Close authenticates with HTTP Basic auth using the API key as the username and an empty password.
# Leads are the top-level object in Close and contacts (with their emails) are nested inside them.
# See https://developer.close.com/resources/leads/ and https://developer.close.com/resources/contacts/

template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="beta",
    free=False,
    type="destination",
    id="template-close",
    name="Close",
    description="Create leads and contacts in Close CRM",
    icon_url="/static/services/close.png",
    category=["CRM", "Customer Success"],
    code_language="hog",
    code="""
let contact := {
    'emails': [
        {
            'email': inputs.email,
            'type': 'office'
        }
    ]
}

for (let key, value in inputs.contactAttributes) {
    if (not empty(value)) {
        contact[key] := value
    }
}

let body := {
    'contacts': [contact]
}

if (not empty(inputs.leadName)) {
    body['name'] := inputs.leadName
}

let res := fetch('https://api.close.com/api/v1/lead/', {
    'method': 'POST',
    'headers': {
        'Authorization': f'Basic {base64Encode(f'{inputs.apiKey}:')}',
        'Content-Type': 'application/json',
    },
    'body': body
})
if (res.status >= 400) {
    throw Error(f'Error from api.close.com (status {res.status}): {res.body}')
}
""".strip(),
    inputs_schema=[
        {
            "key": "apiKey",
            "type": "string",
            "label": "API key",
            "description": "Check out this page to get your API key: https://help.close.com/docs/api-keys",
            "secret": True,
            "required": True,
        },
        {
            "key": "email",
            "type": "string",
            "label": "Email of the contact",
            "description": "Where to find the email for the contact to be created. You can use the filters section to filter out unwanted emails or internal users.",
            "default": "{person.properties.email}",
            "secret": False,
            "required": True,
        },
        {
            "key": "leadName",
            "type": "string",
            "label": "Lead name",
            "description": "The name of the lead (usually the company or organization) the contact belongs to. Leave empty to let Close name the lead after the contact.",
            "default": "{person.properties.company}",
            "secret": False,
            "required": False,
        },
        {
            "key": "contactAttributes",
            "type": "dictionary",
            "label": "Contact attributes",
            "description": "Map of contact fields to send to Close. Keys should match Close contact fields such as 'name', 'title' or 'phones'. See https://developer.close.com/resources/contacts/",
            "default": {"name": "{person.properties.name}", "title": "{person.properties.job_title}"},
            "secret": False,
            "required": True,
        },
    ],
    filters={
        "events": [],
        "actions": [],
        "filter_test_accounts": True,
    },
)
