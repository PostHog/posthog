from posthog.cdp.templates.hog_function_template import HogFunctionTemplate


# See https://documentation.mailgun.com/docs/mailgun/api-reference/openapi-final/tag/Messages


template: HogFunctionTemplate = HogFunctionTemplate(
    status="beta",
    id="template-mailgun-send-email",
    name="Send an email via Mailgun",
    description="Send emails using the Mailgun HTTP API",
    icon_url="/static/services/mailgun.png",
    hog="""
if (empty(inputs.from)) {
    return false
}

let res := fetch(f'https://api.mailgun.net/v3/{domain_name}/messages', {
    'method': 'POST',
    'headers': {
        'Authorization': f'Bearer {base64Encode(f'api:{inputs.api_key}')} ',
        'Content-Type': 'application/json'
    },
    'body': {
        'from': inputs.from,
        'to': inputs.to,
        'subject': inputs.subject,
        'text': inputs.text,
        'html': inputs.html
    }
})

if (res.status >= 400) {
    print('Error from Mailgun API:', res.status, res.body)
}
""".strip(),
    inputs_schema=[
        {
            "key": "domain_name",
            "type": "string",
            "label": "Mailgun Domain Name",
            "description": "The domain name of the Mailgun account",
            "secret": False,
            "required": True,
        },
        {
            "key": "api_key",
            "type": "string",
            "label": "Mailgun API Key",
            "secret": True,
            "required": True,
        },
        {
            "key": "host",
            "type": "choice",
            "choices": [
                {
                    "label": "US (api.mailgun.net)",
                    "value": "api.mailgun.net",
                },
                {
                    "label": "EU (api.eu.mailgun.net)",
                    "value": "api.eu.mailgun.net",
                },
            ],
            "label": "Region",
            "default": "api.eu.mailgun.net",
            "secret": False,
            "required": True,
        },
        {
            "key": "to",
            "type": "string",
            "label": "Email of the user",
            "description": "Email address of the recipient(s). Example: 'Bob <bob@host.com>'. You can use commas to separate multiple recipients",
            "default": "{person.properties.email}",
            "secret": False,
            "required": True,
        },
        {
            "key": "from",
            "type": "string",
            "label": "Email address to be sent from",
            "default": "",
            "secret": False,
            "required": True,
        },
        {
            "key": "subject",
            "type": "string",
            "label": "Email subject",
            "default": "",
            "secret": False,
            "required": True,
        },
        {
            "key": "html",
            "type": "string",
            "label": "HTML content",
            "description": "HTML content of the email",
            "default": "hello world",
            "secret": False,
            "required": False,
        },
        {
            "key": "text",
            "type": "string",
            "label": "Text content",
            "description": "Text content of the email",
            "default": "hello world",
            "secret": False,
            "required": False,
        },
    ],
    filters={
        "events": [{"id": "", "name": "<email trigger event>", "type": "events", "order": 0}],
        "actions": [],
        "filter_test_accounts": True,
    },
)
