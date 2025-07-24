from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="beta",
    free=False,
    type="destination",
    id="template-twilio",
    name="Twilio",
    description="Send SMS via Twilio when an event occurs.",
    icon_url="/static/services/twilio.png",
    category=["Custom"],
    code_language="hog",
    code="""
let encodedTo := encodeURLComponent(inputs.phoneNumber)
let encodedFrom := encodeURLComponent(inputs.fromPhoneNumber)
let encodedSmsBody := encodeURLComponent(f'{inputs.smsBody} - Event: {event.event} at {toDate(event.timestamp)}')
let base64EncodedAuth := base64Encode(f'{inputs.accountSid}:{inputs.authToken}')

let res := fetch(
    f'https://api.twilio.com/2010-04-01/Accounts/{inputs.accountSid}/Messages.json',
    {
        'method': 'POST',
        'headers': {
            'Authorization': f'Basic {base64EncodedAuth}',
            'Content-Type': 'application/x-www-form-urlencoded'
        },
        'body': f'To={encodedTo}&From={encodedFrom}&Body={encodedSmsBody}'
    }
)

if (res.status >= 200 and res.status < 300) {
    print('SMS sent successfully via Twilio!')
} else {
    throw Error('Error sending SMS', res)
}
""".strip(),
    inputs_schema=[
        {
            "key": "accountSid",
            "type": "string",
            "label": "Account SID",
            "secret": False,
            "required": True,
        },
        {
            "key": "authToken",
            "type": "string",
            "label": "Auth Token",
            "secret": True,
            "required": True,
        },
        {
            "key": "fromPhoneNumber",
            "type": "string",
            "label": "From Phone Number",
            "description": "Your Twilio phone number (e.g. +12292109687)",
            "secret": False,
            "required": True,
        },
        {
            "key": "phoneNumber",
            "type": "string",
            "label": "Recipient Phone Number",
            "description": "The phone number to send SMS to (e.g. +491633950489)",
            "secret": False,
            "required": True,
        },
        {
            "key": "smsBody",
            "type": "string",
            "label": "SMS Body Template",
            "description": "Limited to 1600 characters - exceeding this will cause failures.",
            "default": "Event Notification: {event.event} occurred.",
            "secret": False,
            "required": True,
        },
    ],
)
