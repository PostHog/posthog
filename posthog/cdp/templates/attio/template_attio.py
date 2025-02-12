from posthog.cdp.templates.hog_function_template import HogFunctionTemplate

user_filters = {
    "events": [{"id": "$identify", "name": "$identify", "type": "events", "order": 0}],
    "actions": [],
    "filter_test_accounts": True,
}

workspace_filters = {
    "events": [{"id": "$groupidentify", "name": "$groupidentify", "type": "events", "order": 0}],
    "actions": [],
    "filter_test_accounts": True,
}

template_user: HogFunctionTemplate = HogFunctionTemplate(
    status="beta",
    free=False,
    type="destination",
    id="template-attio-user",
    name="Attio",
    description="Create and update User and Person records in Attio",
    icon_url="/static/services/attio.png",
    category=["CRM", "Customer Success"],
    hog="""
let personBody := {
    'data': {
        'values': {
            'email_addresses': [
                {
                    'email_address': inputs.email
                }
            ]
        }
    }
}

let userBody := {
    'data': {
        'values': {
            'user_id': inputs.userId,
            'primary_email_address': [
                {
                    'email_address': inputs.email
                }
            ],
            'person': inputs.email
        }
    }
}

for (let key, value in inputs.personAttributes) {
    if (not empty(value)) {
        personBody.data.values[key] := value
    }
}

for (let key, value in inputs.userAttributes) {
    if (not empty(value)) {
        userBody.data.values[key] := value
    }
}

let personRes := fetch(f'https://api.attio.com/v2/objects/people/records?matching_attribute=email_addresses', {
    'method': 'PUT',
    'headers': {
        'Authorization': f'Bearer {inputs.apiKey}',
        'Content-Type': 'application/json',
    },
    'body': personBody
})


if (personRes.status >= 400) {
    throw Error(f'Error creating Person from api.attio.com (status {personRes.status}): {personRes.body}')
}

let userRes := fetch(f'https://api.attio.com/v2/objects/users/records?matching_attribute=user_id', {
    'method': 'PUT',
    'headers': {
        'Authorization': f'Bearer {inputs.apiKey}',
        'Content-Type': 'application/json',
    },
    'body': userBody
})

if (userRes.status >= 400) {
    throw Error(f'Error creating User from api.attio.com (status {userRes.status}): {userRes.body}')
}
""".strip(),
    inputs_schema=[
        {
            "key": "apiKey",
            "type": "string",
            "label": "Access token",
            "description": "Check out this page to get your API key: https://attio.com/help/reference/integrations-automations/generating-an-api-key",
            "secret": True,
            "required": True,
        },
        {
            "key": "email",
            "type": "string",
            "label": "Email of the user",
            "description": "Where to find the email for the user to be created. You can use the filters section to filter out unwanted emails or internal users.",
            "default": "{person.properties.email}",
            "secret": False,
            "required": True,
        },
        {
            "key": "userId",
            "type": "string",
            "label": "User ID",
            "description": "ID of the user in your database. This is a required attribute for the User record in Attio.",
            "default": "{event.distinct_id}",
            "secret": False,
            "required": True,
        },
        {
            "key": "userAttributes",
            "type": "dictionary",
            "label": "Additional User attributes",
            "description": "This object's keys should be the slugs or IDs of the User attributes you wish to update. For information on potential custom attributes, refer to the attribute type docs: https://developers.attio.com/docs/attribute-types",
            "secret": False,
            "required": True,
        },
        {
            "key": "personAttributes",
            "type": "dictionary",
            "label": "Additional Person attributes",
            "description": "This object's keys should be the slugs or IDs of the Person attributes you wish to update. For information on potential custom attributes, refer to the attribute type docs: https://developers.attio.com/docs/attribute-types",
            "secret": False,
            "required": True,
        },
    ],
    filters=user_filters
)

template_workspace: HogFunctionTemplate = HogFunctionTemplate(
    status="beta",
    free=False,
    type="destination",
    id="template-attio-workspace",
    name="Attio",
    description="Create and update Workspace and Company records in Attio",
    icon_url="/static/services/attio.png",
    category=["CRM", "Customer Success"],
    hog="""
let companyBody := {
    'data': {
        'values': {
            'domains': [
                {
                    'domain': inputs.companyDomain
                }
            ]
        }
    }
}

let workspaceBody := {
    'data': {
        'values': {
            'workspace_id': inputs.workspaceId,
            'company': inputs.companyDomain,
        }
    }
}

for (let key, value in inputs.workspaceAttributes) {
    if (not empty(value)) {
        workspaceBody.data.values[key] := value
    }
}

for (let key, value in inputs.companyAttributes) {
    if (not empty(value)) {
        companyBody.data.values[key] := value
    }
}

let companyRes := fetch(f'https://api.attio.com/v2/objects/companies/records?matching_attribute=domains', {
    'method': 'PUT',
    'headers': {
        'Authorization': f'Bearer {inputs.apiKey}',
        'Content-Type': 'application/json',
    },
    'body': companyBody
})
if (companyRes.status >= 400) {
    throw Error(f'Error creating Company from api.attio.com (status {companyRes.status}): {companyRes.body}')
}

let workspaceRes := fetch(f'https://api.attio.com/v2/objects/workspaces/records?matching_attribute=workspace_id', {
    'method': 'PUT',
    'headers': {
        'Authorization': f'Bearer {inputs.apiKey}',
        'Content-Type': 'application/json',
    },
    'body': workspaceBody
})
if (workspaceRes.status >= 400) {
    throw Error(f'Error creating Workspace from api.attio.com (status {workspaceRes.status}): {workspaceRes.body}')
}
""".strip(),
    inputs_schema=[
        {
            "key": "apiKey",
            "type": "string",
            "label": "Access token",
            "description": "Check out this page to get your API key: https://attio.com/help/reference/integrations-automations/generating-an-api-key",
            "secret": True,
            "required": True,
        },
        {
            "key": "workspaceId",
            "type": "string",
            "label": "Workspace ID",
            "description": "ID of this workspace in your database. Use to reference the relevant Workspace record in Attio",
            "default": "{event.properties.$group_key}",
            "secret": False,
            "required": True,
        },
        {
            "key": "companyDomain",
            "type": "string",
            "label": "Company domain",
            "description": "Domain of the company that this workspace is associated with. Used to reference the relevant Company record in Attio.",
            "default": "{event.properties.$group_set.domain}",
            "secret": False,
            "required": True,
        },
        {
            "key": "workspaceAttributes",
            "type": "dictionary",
            "label": "Additional Workspace attributes",
            "description": "This object's keys should be the slugs or IDs of the Workspace attributes you wish to update. For information on potential custom attributes, refer to the attribute type docs: https://developers.attio.com/docs/attribute-types",
            "secret": False,
            "required": True,
        },
        {
            "key": "companyAttributes",
            "type": "dictionary",
            "label": "Additional Company attributes",
            "description": "This object's keys should be the slugs or IDs of the Company attributes you wish to update. For information on potential custom attributes, refer to the attribute type docs: https://developers.attio.com/docs/attribute-types",
            "secret": False,
            "required": True,
        },
    ],
    filters=workspace_filters
)

template_contact: HogFunctionTemplate = HogFunctionTemplate(
    status="beta",
    free=False,
    type="destination",
    id="template-attio",
    name="Attio",
    description="Create and update contacts in Attio",
    icon_url="/static/services/attio.png",
    category=["Advertisement"],
    hog="""
let body := {
    'data': {
        'values': {
            'email_addresses': [
                {
                    'email_address': inputs.email
                }
            ]
        }
    }
}

for (let key, value in inputs.personAttributes) {
    if (not empty(value)) {
        body.data.values[key] := value
    }
}

let res := fetch(f'https://api.attio.com/v2/objects/people/records?matching_attribute=email_addresses', {
    'method': 'PUT',
    'headers': {
        'Authorization': f'Bearer {inputs.apiKey}',
        'Content-Type': 'application/json',
    },
    'body': body
})
if (res.status >= 400) {
    throw Error(f'Error from api.attio.com (status {res.status}): {res.body}')
}
""".strip(),
    inputs_schema=[
        {
            "key": "apiKey",
            "type": "string",
            "label": "Access token",
            "description": "Check out this page to get your API key: https://attio.com/help/reference/integrations-automations/generating-an-api-key",
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
            "key": "personAttributes",
            "type": "dictionary",
            "label": "Additional Person attributes",
            "description": "This persons keys should be the slugs or IDs of the attributes you wish to update. For information on potential custom attributes, refer to the attribute type docs: https://developers.attio.com/docs/attribute-types",
            "default": {"name": "{person.properties.name}", "job_title": "{person.properties.job_title}"},
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
