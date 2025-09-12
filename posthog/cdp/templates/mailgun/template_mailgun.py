from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

# See https://documentation.mailgun.com/docs/mailgun/api-reference/openapi-final/tag/Messages


template_mailgun_send_email: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="beta",
    free=False,
    type="destination",
    id="template-mailgun-send-email",
    name="Mailgun",
    description="Send emails using the Mailgun HTTP API",
    icon_url="/static/services/mailgun.png",
    category=["Email Marketing"],
    code_language="hog",
    code="""
if (empty(inputs.template.to)) {
    return false
}

fun multiPartFormEncode(data) {
    let boundary := f'---011000010111000001101001'
    let bodyBoundary := f'--{boundary}\\r\\n'
    let body := bodyBoundary

    for (let key, value in data) {
        if (not empty(value)) {
            body := f'{body}Content-Disposition: form-data; name="{key}"\\r\\n\\r\\n{value}\\r\\n{bodyBoundary}'
        }
    }

    return {
        'body': body,
        'contentType': f'multipart/form-data; boundary={boundary}'
    }
}

let form := multiPartFormEncode({
    'from': inputs.template.from,
    'to': inputs.template.to,
    'subject': inputs.template.subject,
    'text': inputs.template.text,
    'html': inputs.template.html
})

let res := fetch(f'https://{inputs.host}/v3/{inputs.domain_name}/messages', {
    'method': 'POST',
    'headers': {
        'Authorization': f'Basic {base64Encode(f'api:{inputs.api_key}')}',
        'Content-Type': form.contentType
    },
    'body': form.body
})

if (res.status >= 400) {
    throw Error(f'Error from mailgun api (status {res.status}): {res.body}')
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
            "key": "template",
            "type": "email",
            "label": "Email template",
            "default": {
                "to": "{person.properties.email}",
            },
            "secret": False,
            "required": True,
        },
    ],
    filters={
        "events": [{"id": "", "name": "<email trigger event>", "type": "events", "order": 0}],
        "actions": [],
        "filter_test_accounts": True,
    },
)
