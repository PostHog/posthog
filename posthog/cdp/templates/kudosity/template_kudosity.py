from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="beta",
    free=False,
    type="destination",
    id="template-kudosity-sms",
    name="Kudosity SMS",
    description="Send SMS alerts via Kudosity when PostHog events or metrics cross thresholds. Ideal for operational monitoring, on-call notifications, and business metric tracking.",
    icon_url="/static/services/kudosity.png",
    category=["SMS & Push Notifications", "Monitoring & Alerts"],
    code_language="hog",
    code="""
// Validate required fields
if (empty(inputs.recipient)) {
    print('No recipient phone number set. Skipping...')
    return
}

if (empty(inputs.message)) {
    print('No message set. Skipping...')
    return
}

// Construct SMS payload
let body := {
    'message': inputs.message,
    'sender': inputs.sender,
    'recipient': inputs.recipient
}

// Add optional fields
if (not empty(inputs.message_ref)) {
    body['message_ref'] := inputs.message_ref
}

if (inputs.track_links) {
    body['track_links'] := true
}

// Debug logging
if (inputs.debug) {
    print('==== Kudosity SMS Alert ====')
    print('Recipient:', inputs.recipient)
    print('Message:', inputs.message)
    print('Sender:', inputs.sender)
}

// Send SMS via Kudosity API
let res := fetch('https://api.transmitmessage.com/v2/sms', {
    'method': 'POST',
    'headers': {
        'x-api-key': inputs.api_key,
        'Content-Type': 'application/json'
    },
    'body': body
})

// Handle errors
if (res.status >= 400) {
    throw Error(f'Error from Kudosity API (status {res.status}): {res.body}')
}

if (inputs.debug) {
    print('✓ SMS alert sent successfully')
}
""".strip(),
    inputs_schema=[
        {
            "key": "api_key",
            "type": "string",
            "label": "Kudosity API Key",
            "description": "Your Kudosity API key from Settings → API Keys. If you don’t have one yet, sign up for a free developer trial at https://kudosity.com/developer-trial. This authenticates all SMS requests to Kudosity's API.",
            "default": "This value is secret and is not displayed here",
            "secret": True,
            "required": True,
        },
        {
            "key": "sender",
            "type": "string",
            "label": "Sender Number or ID",
            "description": "Your approved sender number or alphanumeric ID. Use E.164 format (e.g. +61412345678) for numbers. Alphanumeric IDs (max 11 characters, e.g. 'MyCompany') are allowed. Must be pre-approved in your Kudosity account.",
            "default": "61XXXXXXXXX",
            "secret": False,
            "required": True,
        },
        {
            "key": "recipient",
            "type": "string",
            "label": "Recipient Phone Number",
            "description": "Phone number to receive SMS alerts, in E.164 format (e.g. +61412345678). You can also use PostHog variables like {person.properties.phone} or {event.properties.oncall_number} for dynamic routing.",
            "default": "",
            "secret": False,
            "required": True,
        },
        {
            "key": "message",
            "type": "string",
            "label": "Message Template",
            "description": "The text body of your alert message. Use PostHog variables inside curly braces, e.g.: ⚠️ {event.properties.insight_name} is {event.properties.current_value} (threshold: {event.properties.threshold_value}). Messages over 160 characters will be split automatically.",
            "default": "🚨 Alert: {event.properties.insight_name} is {event.properties.current_value} (threshold: {event.properties.threshold_value})",
            "secret": False,
            "required": True,
        },
        {
            "key": "message_ref",
            "type": "string",
            "label": "Message Reference",
            "description": "Optional custom ID for tracking this alert (max 500 chars). You can include variables such as {event.properties.alert_id} to correlate with Kudosity delivery logs.",
            "default": "alert_{event.properties.alert_id}",
            "secret": False,
            "required": False,
        },
        {
            "key": "track_links",
            "type": "boolean",
            "label": "Track Links",
            "description": "Automatically shorten and track links included in the SMS message. Useful for marketing or engagement analytics.",
            "default": False,
            "secret": False,
            "required": False,
        },
        {
            "key": "debug",
            "type": "boolean",
            "label": "Debug Mode",
            "description": "Enables detailed logging for delivery and API responses. Turn on for troubleshooting or testing only.",
            "default": False,
            "secret": False,
            "required": False,
        },
    ],
)
