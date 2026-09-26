from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

# Bsed off of https://developer.zendesk.com/api-reference/ticketing/users/users/#create-or-update-user

template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="beta",
    free=False,
    type="destination",
    id="template-zendesk",
    name="Zendesk",
    description="Update contacts in Zendesk",
    category=["Customer Success"],
    icon_url="/static/services/zendesk.png",
    code_language="hog",
    code="""
if (empty(inputs.email) or empty(inputs.name)) {
    print('`email` or `name` input is empty. Not creating a contact.')
    return
}

let subdomain := inputs.subdomain
let authorization := ''
if (not empty(inputs.oauth)) {
    subdomain := inputs.oauth.subdomain
    authorization := f'Bearer {inputs.oauth.access_token}'
} else if (not empty(inputs.subdomain) and not empty(inputs.admin_email) and not empty(inputs.token)) {
    authorization := f'Basic {base64Encode(f'{inputs.admin_email}/token:{inputs.token}')}'
} else {
    throw Error('Connect a Zendesk account, or enter a Zendesk subdomain, API user email, and API token.')
}

let body := {
    'user': {
        'email': inputs.email,
        'name': inputs.name,
        'skip_verify_email': true,
        'user_fields': {}
    }
}

for (let key, value in inputs.attributes) {
    if (not empty(value) and key != 'email' and key != 'name') {
        body.user.user_fields[key] := value
    }
}

fetch(f'https://{subdomain}.zendesk.com/api/v2/users/create_or_update', {
  'headers': {
    'Authorization': authorization,
    'Content-Type': 'application/json'
  },
  'body': body,
  'method': 'POST'
});
""".strip(),
    inputs_schema=[
        {
            "key": "oauth",
            "type": "integration",
            "integration": "zendesk",
            "label": "Zendesk account",
            "secret": False,
            "required": False,
            "description": "Connect your Zendesk account. If you connect an account, you can leave the API token fields empty.",
        },
        {
            "key": "subdomain",
            "type": "string",
            "label": "Zendesk subdomain",
            "description": "Only needed with an API token. Your Zendesk URL has two parts: a subdomain name you chose when you set up your account, followed by zendesk.com (for example: mycompany.zendesk.com). Enter the subdomain name.",
            "secret": False,
            "required": False,
        },
        {
            "key": "admin_email",
            "type": "string",
            "label": "API user email",
            "secret": True,
            "required": False,
            "description": "Only needed with an API token. Enter the email of an admin in Zendesk. Activity using the API token will be attributed to this user.",
        },
        {
            "key": "token",
            "type": "string",
            "label": "API token",
            "secret": True,
            "required": False,
            "hint": "Only needed if you do not connect a Zendesk account. Zendesk is retiring API tokens.",
        },
        {
            "key": "email",
            "type": "string",
            "label": "User email",
            "default": "{person.properties.email}",
            "secret": False,
            "required": True,
            "hint": "The email of the user you want to create or update.",
        },
        {
            "key": "name",
            "type": "string",
            "label": "User name",
            "default": "{person.properties.name}",
            "secret": False,
            "required": True,
            "hint": "The name of the user you want to create or update.",
        },
        {
            "key": "attributes",
            "type": "dictionary",
            "label": "Attribute mapping",
            "description": "Map of Zendesk user fields and their values. You'll need to create User fields in Zendesk for these to work.",
            "default": {
                "phone": "{person.properties.phone}",
                "plan": "{person.properties.plan}",
            },
            "secret": False,
            "required": False,
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
