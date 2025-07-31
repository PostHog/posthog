from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="beta",
    free=False,
    type="destination",
    id="template-mailchimp",
    name="Mailchimp",
    description="Updates a contact in Mailchimp and subscribes new ones.",
    icon_url="/static/services/mailchimp.png",
    category=["Email Marketing"],
    code_language="hog",
    code="""
if (empty(inputs.email)) {
    print('No email set. Skipping...')
    return
}

let email := lower(inputs.email)
let subscriberHash := md5Hex(email)

let properties := {}


for (let key, value in inputs.properties) {
    if (not empty(value)) {
        properties[key] := value
    }
}

if (inputs.include_all_properties) {
    for (let key, value in event.properties) {
        if (not empty(value) and not key like '$%') {
            properties[key] := value
        }
    }
}

let userStatus := fetch(f'https://{inputs.dataCenterId}.api.mailchimp.com/3.0/lists/{inputs.audienceId}/members/{subscriberHash}', {
    'method': 'GET',
    'headers': {
        'Authorization': f'Bearer {inputs.apiKey}',
        'Content-Type': 'application/json'
    }
})

if (userStatus.status == 404 or userStatus.status == 200) {
    let res := fetch(f'https://{inputs.dataCenterId}.api.mailchimp.com/3.0/lists/{inputs.audienceId}/members/{subscriberHash}', {
        'method': 'PUT',
        'headers': {
            'Authorization': f'Bearer {inputs.apiKey}',
            'Content-Type': 'application/json'
        },
        'body': {
            'email_address': inputs.email,
            'status_if_new': inputs.doubleOptIn ? 'pending' : 'subscribed',
            'merge_fields': properties
        }
    })
    if (res.status >= 400) {
        throw Error(f'Error from api.mailchimp.com (status {userStatus.status}): {userStatus.body}')
    }
} else if (userStatus.status >= 400) {
    throw Error(f'Error from api.mailchimp.com (status {userStatus.status}): {userStatus.body}')
}

""".strip(),
    inputs_schema=[
        {
            "key": "apiKey",
            "type": "string",
            "label": "Mailchimp API Key",
            "description": "See the docs here: https://mailchimp.com/help/about-api-keys/",
            "secret": True,
            "required": True,
        },
        {
            "key": "audienceId",
            "type": "string",
            "label": "Mailchimp audience ID",
            "description": "See the docs here: https://mailchimp.com/help/find-audience-id/",
            "secret": False,
            "required": True,
        },
        {
            "key": "dataCenterId",
            "type": "string",
            "label": "Mailchimp data center ID",
            "description": "You can find your Datacenter ID in the Mailchimp url in your browser when you're logged in. It's the 'us1' in 'https://us1.admin.mailchimp.com/lists/'",
            "secret": False,
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
            "key": "doubleOptIn",
            "type": "boolean",
            "label": "Enable double opt-in",
            "description": "If enabled, Mailchimp sends a confirmation email to that user, and that email is tagged with a pending subscriber status. The subscriber status automatically changes to subscribed once the user confirms the email.",
            "default": False,
            "secret": False,
            "required": True,
        },
        {
            "key": "include_all_properties",
            "type": "boolean",
            "label": "Include all event properties",
            "description": "If set, all person properties will be included. Individual properties can be overridden below.",
            "default": False,
            "secret": False,
            "required": True,
        },
        {
            "key": "properties",
            "type": "dictionary",
            "label": "Merge field",
            "description": "Map of Mailchimp merge fields and their values. You can use the filters section to filter out unwanted events. Check out this page for more details: https://mailchimp.com/developer/marketing/docs/merge-fields/#add-merge-data-to-contacts",
            "default": {
                "FNAME": "{person.properties.firstname}",
                "LNAME": "{person.properties.lastname}",
                "COMPANY": "{person.properties.company}",
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
