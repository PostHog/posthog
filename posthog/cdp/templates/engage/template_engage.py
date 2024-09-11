from posthog.cdp.templates.hog_function_template import HogFunctionTemplate

template: HogFunctionTemplate = HogFunctionTemplate(
    status="beta",
    id="template-engage-so",
    name="Send events to Engage.so",
    description="Send events to Engage.so",
    icon_url="/static/services/engage.png",
    hog="""
let body := event

body['event'] := event.name

fetch('https://api.engage.so/posthog', {
    'method': 'POST',
    'headers': {
        'Authorization': f'Basic {base64Encode(f'{inputs.public_key}:{inputs.private_key}')}',
        'Content-Type': 'application/json'
    },
    'body': body
})
""".strip(),
    inputs_schema=[
        {
            "key": "public_key",
            "type": "string",
            "label": "Public key",
            "description": "Get your public key from your Engage dashboard (Settings -> Account)",
            "secret": True,
            "required": True,
        },
        {
            "key": "private_key",
            "type": "string",
            "label": "Private key",
            "description": "Get your private key from your Engage dashboard (Settings -> Account)",
            "secret": True,
            "required": True,
        },
    ],
)
