from posthog.cdp.templates.hog_function_template import HogFunctionTemplate

# Based off of https://github.com/PostHog/posthog-engage-so-plugin

template: HogFunctionTemplate = HogFunctionTemplate(
    status="alpha",
    id="template-engage-so",
    name="Send events to Engage.so",
    description="Send events to Engage.so",
    icon_url="/api/projects/@current/hog_functions/icon/?id=engage.so",
    hog="""
fetch(f'https://api.engage.so/posthog', {
    'method': 'POST',
    'headers': {
        'Authorization': f'Basic {base64Encode(f'{inputs.public_key}:{inputs.private_key}')}',
        'Content-Type': 'application/json'
    },
    'body': {
        'event': event.name,
        'distinct_id': event.distinct_id,
        'properties': event.properties,
        'person': person.properties
    }
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
