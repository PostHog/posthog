from posthog.cdp.templates.hog_function_template import HogFunctionTemplate


template: HogFunctionTemplate = HogFunctionTemplate(
    status="beta",
    id="template-zendesk",
    name="Update contacts in Zendesk",
    description="Update contacts in Zendesk",
    icon_url="/api/projects/@current/hog_functions/icon/?id=zendesk.com",
    hog="""

let headers := {
    'Authorization': f'Basic {base64Encode(f'{inputs.email}/token:{inputs.token}')}',
    'Content-Type': 'application/json'
}

fetch(inputs.url, {
  'headers': inputs.headers,
  'body': inputs.body,
  'method': inputs.method
});
""".strip(),
    inputs_schema=[
        {
            "key": "subdomain",
            "type": "string",
            "label": "Zendesk subdomain",
            "description": "Generally, Your Zendesk URL has two parts: a subdomain name you chose when you set up your account, followed by zendesk.com (for example: mycompany.zendesk.com). Please share the subdomain name with us so we can set up your account.",
            "secret": False,
            "required": True,
        },
        {
            "key": "admin_email",
            "type": "string",
            "label": "API user email",
            "default": "email@admin.com",
            "required": True,
            "description": "Enter the email for admin of your Zendesk account.",
        },
        {
            "key": "token",
            "type": "string",
            "label": "API token",
            "required": True,
            "hint": "Enter your Zendesk API Token",
        },
    ],
    filters={
        "events": [{"id": "$identify", "name": "$identify", "type": "events", "order": 0}],
        "actions": [],
        "filter_test_accounts": True,
    },
)
