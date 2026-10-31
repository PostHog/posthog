from products.cdp.backend.templates.hog_function_template import HogFunctionTemplateDC

# Bsed off of https://developer.zendesk.com/api-reference/ticketing/users/users/#create-or-update-user

template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="stable",
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

// Zendesk is retiring API tokens, so exchange the OAuth client for a short-lived access token on each run.
let tokenRes := fetch(f'https://{inputs.subdomain}.zendesk.com/oauth/tokens', {
  'headers': {
    'Content-Type': 'application/json'
  },
  'body': {
    'grant_type': 'client_credentials',
    'client_id': inputs.client_id,
    'client_secret': inputs.client_secret,
    'scope': 'users:write',
    'expires_in': 300
  },
  'method': 'POST'
});

if (tokenRes.status >= 400 or empty(tokenRes.body.access_token)) {
    throw Error(f'Could not get an access token from {inputs.subdomain}.zendesk.com (status {tokenRes.status}). Check the OAuth client identifier and secret, and that the client allows the client credentials grant.')
}

let res := fetch(f'https://{inputs.subdomain}.zendesk.com/api/v2/users/create_or_update', {
  'headers': {
    'Authorization': f'Bearer {tokenRes.body.access_token}',
    'Content-Type': 'application/json'
  },
  'body': body,
  'method': 'POST'
});

if (res.status >= 400) {
    throw Error(f'Error from {inputs.subdomain}.zendesk.com (status {res.status}): {res.body}')
}
""".strip(),
    inputs_schema=[
        {
            "key": "subdomain",
            "type": "string",
            "label": "Zendesk subdomain",
            "description": "The first part of your Zendesk URL. For mycompany.zendesk.com, enter mycompany.",
            "secret": False,
            "required": True,
        },
        {
            "key": "client_id",
            "type": "string",
            "label": "OAuth client identifier",
            "description": "In Zendesk Admin Center, go to Apps and integrations > APIs > OAuth clients. Create a confidential client that allows the client credentials grant and the users:write scope, then copy its identifier here. Changes are attributed to the admin who created the client.",
            "secret": False,
            "required": True,
        },
        {
            "key": "client_secret",
            "type": "string",
            "label": "OAuth client secret",
            "description": "The secret Zendesk shows when you create the OAuth client.",
            "secret": True,
            "required": True,
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
