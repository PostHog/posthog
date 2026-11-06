from products.cdp.backend.templates.hog_function_template import HogFunctionTemplateDC

template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="beta",
    free=False,
    type="destination",
    id="template-knock2",
    name="Knock2",
    description="Send identified people to Knock2 to name anonymous website visitors",
    icon_url="/static/services/knock2.png",
    category=["CRM", "Customer Success"],
    filters={
        # A person becomes known at $identify, which is the moment worth
        # sending. Everything else is noise on this destination, but it is left
        # editable rather than enforced in Hog so a project that identifies on
        # its own event can still use it.
        "events": [{"id": "$identify", "name": "$identify", "type": "events", "order": 0}],
        "actions": [],
        "filter_test_accounts": True,
    },
    code_language="hog",
    code="""
if (empty(inputs.distinctId)) {
    print('No distinct ID set. Skipping...')
    return
}

// An answer with neither an email nor a name names nobody, and Knock2 rejects
// it. Returning early keeps those events out of the function's error log.
if (empty(inputs.email) and empty(inputs.name)) {
    print('No email or name on this person. Skipping...')
    return
}

let body := {
    'distinct_id': inputs.distinctId,
    'token': inputs.projectToken,
    'email': inputs.email,
    'name': inputs.name,
    'person_id': inputs.personId
}

let res := fetch('https://api.knock2.ai/v1/posthog/identify', {
    'method': 'POST',
    'headers': {
        'Authorization': f'Bearer {inputs.apiKey}',
        'Content-Type': 'application/json',
    },
    'body': body
})

if (res.status >= 400) {
    throw Error(f'Error from api.knock2.ai (status {res.status}): {res.body}')
}
""".strip(),
    inputs_schema=[
        {
            "key": "apiKey",
            "type": "string",
            "label": "Knock2 API key",
            "description": "Create one in Knock2 under Settings > API Keys, with the identities:write scope. See https://knock2.ai/integrations/posthog",
            "secret": True,
            "required": True,
        },
        {
            "key": "projectToken",
            "type": "string",
            "label": "PostHog project API key",
            "description": "The public project API key this data belongs to (starts with phc_), from Project settings. Knock2 already sees this token in your visitors' browsers and uses it to match them to the people you send here.",
            "secret": False,
            "required": True,
        },
        {
            "key": "distinctId",
            "type": "string",
            "label": "Distinct ID",
            "description": "The PostHog distinct ID of the person who identified. Leave as the default unless you know you need another value: this is the ID posthog-js stores in the browser, and it is what Knock2 matches against the visitor on your site. The PostHog person ID ({person.id}) will not match anything.",
            "default": "{event.distinct_id}",
            "secret": False,
            "required": True,
        },
        {
            "key": "email",
            "type": "string",
            "label": "Email",
            "description": "Where to find the person's email. Use the filters above to keep your own staff and test users out.",
            "default": "{person.properties.email}",
            "secret": False,
            "required": False,
        },
        {
            "key": "name",
            "type": "string",
            "label": "Name",
            "default": "{person.properties.name}",
            "secret": False,
            "required": False,
        },
        {
            "key": "personId",
            "type": "string",
            "label": "PostHog person ID",
            "description": "Stored alongside the answer so you can trace a Knock2 contact back to the PostHog person it came from.",
            "default": "{person.id}",
            "secret": False,
            "required": False,
        },
    ],
)
