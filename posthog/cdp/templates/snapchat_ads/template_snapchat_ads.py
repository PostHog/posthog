from posthog.cdp.templates.hog_function_template import HogFunctionTemplate

template: HogFunctionTemplate = HogFunctionTemplate(
    status="alpha",
    type="destination",
    id="template-snapchat-ads",
    name="Snapchat Ads Conversions",
    description="Send conversion events to Snapchat Ads",
    icon_url="/static/services/snapchat.png",
    category=["Advertisement"],
    hog="""
let body := {
    'data': [
        {
            'event_name': inputs.eventName,
            'action_source': inputs.actionSource,
            'event_time': inputs.eventTime,
            'user_data': {},
            'custom_data': {}
        }
    ]
}

if (not empty(event.properties.$current_url)) body.data.1.event_source_url := event.properties.$current_url

for (let key, value in inputs.userData) {
    if (not empty(value)) {
        body.data.1.user_data[key] := value
    }
}

for (let key, value in inputs.customData) {
    if (not empty(value)) {
        body.data.1.custom_data[key] := value
    }
}

let res := fetch(f'https://tr.snapchat.com/v3/{inputs.pixelId}/events?access_token={inputs.accessToken}', {
    'method': 'POST',
    'headers': {
        'Content-Type': 'application/json',
    },
    'body': body
})
if (res.status >= 400) {
    throw Error(f'Error from tr.snapchat.com (status {res.status}): {res.body}')
}
""".strip(),
    inputs_schema=[
        {
            "key": "accessToken",
            "type": "string",
            "label": "Access token",
            "description": "Check out this page on how to obtain such a token: https://developers.snap.com/api/marketing-api/Conversions-API/GetStarted#access-token",
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
            "default": "{toUnixTimestampMilli(event.timestamp)}",
            "secret": False,
            "required": True,
        },
        {
            "key": "actionSource",
            "label": "Action source",
            "type": "choice",
            "choices": [
                {
                    "label": "WEB - Conversion was made on your website.",
                    "value": "WEB",
                },
                {
                    "label": "MOBILE_APP - Conversion was made on your mobile app.",
                    "value": "MOBILE_APP",
                },
                {
                    "label": "OFFLINE - Conversion happened in a way that is not listed.",
                    "value": "OFFLINE",
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
            "description": "A map that contains customer information data. See this page for options: https://developers.snap.com/api/marketing-api/Conversions-API/Parameters#user-data-parameters",
            "default": {
                "em": "{sha256Hex(person.properties.email ?? '')}",
                "ph": "{sha256Hex(person.properties.phone ?? '')}",
                "sc_click_id": "{person.properties.sccid ?? person.properties.$initial_sccid ?? ''}",
            },
            "secret": False,
            "required": True,
        },
        {
            "key": "customData",
            "type": "dictionary",
            "label": "Custom data",
            "description": "A map that contains custom data. See this page for options: https://developers.snap.com/api/marketing-api/Conversions-API/Parameters#custom-data-parameters",
            "default": {
                "currency": "USD",
                "value": "{event.properties.price}",
                "event_id": "{event.uuid}",
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
