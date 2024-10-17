from posthog.cdp.templates.hog_function_template import HogFunctionTemplate

template: HogFunctionTemplate = HogFunctionTemplate(
    status="alpha",
    id="template-meta-ads",
    name="Meta Ads Conversions",
    description="Send conversion events to Meta Ads",
    icon_url="/static/services/meta-ads.png",
    category=["Advertisement"],
    hog="""
let res := fetch(f'https://graph.facebook.com/v21.0/{inputs.pixelId}/events', {
    'method': 'POST',
    'headers': {
        'Content-Type': 'application/json',
    },
    'body': {
        'data': [
            {
                'event_name': inputs.eventName,
                'event_time': inputs.eventTime,
                'action_source': inputs.actionSource,
                'user_data': inputs.userData
            }
        ],
        'access_token': inputs.accessToken
    }
})
if (res.status >= 400) {
    throw Error(f'Error from graph.facebook.com (status {res.status}): {res.body}')
}
""".strip(),
    inputs_schema=[
        {
            "key": "accessToken",
            "type": "string",
            "label": "Access token",
            "description": "Check out this page on how to obtain such a token: https://developers.facebook.com/docs/marketing-api/conversions-api/get-started",
            "secret": True,
            "required": True,
        },
        {
            "key": "pixelId",
            "type": "string",
            "label": "Pixel ID",
            "description": "You must obtain a Pixel ID to use the Conversions API. If you’ve already set up a Pixel for your website, we recommend that you use the same Pixel ID for your browser and server events.",
            "secret": False,
            "required": True,
        },
        {
            "key": "eventName",
            "type": "string",
            "label": "Event name",
            "description": "A standard event or custom event name.",
            "default": "{event.event}",
            "secret": False,
            "required": True,
        },
        {
            "key": "eventTime",
            "type": "string",
            "label": "Event time",
            "description": "A Unix timestamp in seconds indicating when the actual event occurred. You must send this date in GMT time zone.",
            "default": "{toInt(toUnixTimestamp(event.timestamp))}",
            "secret": False,
            "required": True,
        },
        {
            "key": "actionSource",
            "label": "Action source",
            "type": "choice",
            "choices": [
                {
                    "label": "Email - Conversion happened over email.",
                    "value": "email",
                },
                {
                    "label": "Website - Conversion was made on your website.",
                    "value": "website",
                },
                {
                    "label": "App - Conversion was made on your mobile app.",
                    "value": "app",
                },
                {
                    "label": "Phone call - Conversion was made over the phone.",
                    "value": "phone_call",
                },
                {
                    "label": "Chat - Conversion was made via a messaging app, SMS, or online messaging feature.",
                    "value": "chat",
                },
                {
                    "label": "Physical store - Conversion was made in person at your physical store.",
                    "value": "physical_store",
                },
                {
                    "label": "System generated - Conversion happened automatically, for example, a subscription renewal that’s set to auto-pay each month.",
                    "value": "system_generated",
                },
                {
                    "label": "Business messaging - Conversion was made from ads that click to Messenger, Instagram or WhatsApp.",
                    "value": "business_messaging",
                },
                {
                    "label": "Other - Conversion happened in a way that is not listed.",
                    "value": "other",
                },
            ],
            "description": "This field allows you to specify where your conversions occurred. Knowing where your events took place helps ensure your ads go to the right people.",
            "default": "website",
            "secret": False,
            "required": True,
        },
        {
            "key": "userData",
            "type": "dictionary",
            "label": "User data",
            "description": "A map that contains customer information data. See this page for options: https://developers.facebook.com/docs/marketing-api/conversions-api/parameters/customer-information-parameters",
            "default": {
                "em": "{sha256Hex(person.properties.email)}",
                "fn": "{sha256Hex(person.properties.first_name)}",
                "ln": "{sha256Hex(person.properties.last_name)}",
            },
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
