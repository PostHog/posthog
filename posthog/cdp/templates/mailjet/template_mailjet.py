from posthog.cdp.templates.hog_function_template import HogFunctionTemplate


# See https://dev.mailjet.com/email/reference/contacts/contact-list/

common_inputs_schemas = [
    {
        "key": "api_key",
        "type": "string",
        "label": "Mailjet API Key",
        "secret": True,
        "required": True,
    },
    {
        "key": "email",
        "type": "string",
        "label": "Email of the user",
        "description": "Where to find the email for the user to be checked with Mailjet",
        "default": "{person.properties.email}",
        "secret": False,
        "required": True,
    },
]

common_filters = {
    "events": [{"id": "$identify", "name": "$identify", "type": "events", "order": 0}],
    "actions": [],
    "filter_test_accounts": True,
}


template_create_contact: HogFunctionTemplate = HogFunctionTemplate(
    status="beta",
    id="template-mailjet-create-contact",
    name="Add contacts to Mailjet",
    description="Updates a contact in Mailjet",
    icon_url="/static/services/mailjet.png",
    hog="""
if (empty(inputs.email)) {
    return false
}

fetch(f'https://api.mailjet.com/v3/REST/contact/', {
    'method': 'POST',
    'headers': {
        'Authorization': f'Bearer {inputs.api_key}',
        'Content-Type': 'application/json'
    },
    'body': {
        'Email': inputs.email,
        'Name': inputs.name,
        'IsExcludedFromCampaigns': inputs.is_excluded_from_campaigns
    }
})
""".strip(),
    inputs_schema=[
        *common_inputs_schemas,
        {
            "key": "name",
            "type": "string",
            "label": "Name",
            "description": "Name of the contact",
            "default": "{person.properties.first_name} {person.properties.last_name}",
            "secret": False,
            "required": False,
        },
        {
            "key": "is_excluded_from_campaigns",
            "type": "boolean",
            "label": "Is excluded from campaigns",
            "description": "Whether the contact should be excluded from campaigns",
            "default": False,
            "secret": False,
            "required": False,
        },
    ],
    filters=common_filters,
)


template_update_contact_list: HogFunctionTemplate = HogFunctionTemplate(
    status="beta",
    id="template-mailjet-update-contact-list",
    name="Update a Mailjet contact list",
    description="Updates a contact in Mailjet",
    icon_url="/static/services/mailjet.png",
    hog="""
if (empty(inputs.email)) {
    return false
}

fetch(f'https://api.mailjet.com/v3/REST/contact/{inputs.email}/managecontactlists', {
    'method': 'POST',
    'headers': {
        'Authorization': f'Bearer {inputs.api_key}',
        'Content-Type': 'application/json'
    },
    'body': {
        'ContactsLists':[
            {
                'Action': inputs.action,
                'ListID': inputs.contact_list_id
            },
        ]
    }
})
""".strip(),
    inputs_schema=[
        *common_inputs_schemas,
        {
            "key": "contact_list_id",
            "type": "string",
            "label": "Contact list ID",
            "description": "ID of the contact list",
            "secret": False,
            "required": True,
        },
        {
            "key": "action",
            "type": "choice",
            "label": "Action",
            "secret": False,
            "default": "addnoforce",
            "required": True,
            "choices": [
                {
                    "label": "Add",
                    "value": "addnoforce",
                },
                {
                    "label": "Add (force)",
                    "value": "addforce",
                },
                {
                    "label": "Remove",
                    "value": "remove",
                },
                {
                    "label": "Unsubscribe",
                    "value": "unsub",
                },
            ],
        },
    ],
    filters=common_filters,
)
