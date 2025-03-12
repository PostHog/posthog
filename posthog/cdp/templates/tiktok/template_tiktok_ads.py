from posthog.cdp.templates.hog_function_template import HogFunctionTemplate

template: HogFunctionTemplate = HogFunctionTemplate(
    status="alpha",
    free=False,
    type="destination",
    id="template-tiktok-ads",
    name="TikTok Ads Conversions",
    description="Send conversion events to TikTok Ads",
    icon_url="/static/services/tiktok.png",
    category=["Advertisement"],
    hog="""
let body := {
    'event_source': 'web',
    'event_source_id': inputs.pixelId,
    'data': [
        {
            'event': inputs.eventName,
            'event_time': toUnixTimestamp(event.timestamp),
            'event_id': event.uuid,
            'user': {},
            'properties': {},
            'page': {}
        }
    ]
}

if (not empty(inputs.testEventCode)) {
    body.test_event_code := inputs.testEventCode
}

for (let key, value in inputs.userProperties) {
    // e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 is an empty string hashed
    if (not empty(value) and value != 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855') {
        body.data.1.user[key] := value
    }
}

for (let key, value in inputs.propertyProperties) {
    // e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 is an empty string hashed
    if (not empty(value) and value != 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855') {
        body.data.1.properties[key] := value
    }
}

if (not empty(event.properties.$current_url)) body.data.1.page.url := event.properties.$current_url
if (not empty(event.properties.$referrer)) body.data.1.page.referrer := event.properties.$referrer

let res := fetch(f'https://business-api.tiktok.com/open_api/v1.3/event/track/', {
    'method': 'POST',
    'headers': {
        'Content-Type': 'application/json',
        'Access-Token': inputs.accessToken
    },
    'body': body
})
if (res.status >= 400) {
    throw Error(f'Error from business-api.tiktok.com (status {res.status}): {res.body}')
}
""".strip(),
    inputs_schema=[
        {
            "key": "accessToken",
            "type": "string",
            "label": "Access token",
            "description": "Check out this page on how to obtain such a token: https://business-api.tiktok.com/portal/docs?id=1771101027431425",
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
            "key": "userProperties",
            "type": "dictionary",
            "label": "User properties",
            "description": "A map that contains customer information data. See this page for options: https://business-api.tiktok.com/portal/docs?id=1807346079965186",
            "default": {
                "email": "{sha256Hex(person.properties.email ?? '')}",
                "ttclid": "{person.properties.ttclid ?? person.properties.$initial_ttclid}",
                "phone": "{sha256Hex(person.properties.phone ?? '')}",
                "ip": "{person.properties.$ip}",
                "user_agent": "{person.properties.$raw_user_agent}",
            },
            "secret": False,
            "required": True,
        },
        {
            "key": "propertyProperties",
            "type": "dictionary",
            "label": "Property properties",
            "description": "A map that contains customer information data. See this page for options: https://business-api.tiktok.com/portal/docs?id=1807346079965186",
            "default": {
                "currency": "USD",
                "value": "{event.properties.price}",
            },
            "secret": False,
            "required": True,
        },
        {
            "key": "testEventCode",
            "type": "string",
            "label": "Test Event Code",
            "description": "Use this field to specify that events should be test events rather than actual traffic. You'll want to remove your Test Event Code when sending real traffic through this integration.",
            "default": "",
            "secret": False,
            "required": False,
        },
    ],
    filters={
        "events": [],
        "actions": [],
        "filter_test_accounts": True,
    },
)
