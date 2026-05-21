from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="alpha",
    free=False,
    type="destination",
    id="template-meta-ads",
    name="Meta Ads Conversions",
    description="Send conversion events to Meta Ads",
    icon_url="/static/services/meta-ads.png",
    category=["Advertisement"],
    code_language="hog",
    code="""
let body := {
    'data': [
        {
            'event_name': inputs.eventName,
            'event_id': inputs.eventId,
            'event_time': inputs.eventTime,
            'action_source': inputs.actionSource,
            'user_data': {},
            'custom_data': {}
        }
    ],
    'access_token': inputs.accessToken
}

if (not empty(inputs.testEventCode)) {
    body.test_event_code := inputs.testEventCode
}

if (not empty(inputs.eventSourceUrl)) {
    body.data.1.event_source_url := inputs.eventSourceUrl
}

// Helper function to parse JSON arrays from string values
fn parseValueIfArray(value) {
    if (typeof(value) == 'string') {
        let trimmed := trim(value)
        if (startsWith(trimmed, '[')) {
            try {
                return jsonParse(trimmed)
            } catch {
                return value
            }
        }
    }
    return value
}

for (let key, value in inputs.userData) {
    if (not empty(value)) {
        body.data.1.user_data[key] := parseValueIfArray(value)
    }
}

for (let key, value in inputs.customData) {
    if (not empty(value)) {
        body.data.1.custom_data[key] := parseValueIfArray(value)
    }
}

let res := fetch(f'https://graph.facebook.com/v21.0/{inputs.pixelId}/events', {
    'method': 'POST',
    'headers': {
        'Content-Type': 'application/json',
    },
    'body': body
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
            "description": "A system user access token for the Conversions API (looks like a long opaque string, e.g. `EAA...`). Generate one in Meta Events Manager → your dataset → Settings → Conversions API → Generate access token, or follow the full guide at https://developers.facebook.com/docs/marketing-api/conversions-api/get-started.",
            "secret": True,
            "required": True,
        },
        {
            "key": "pixelId",
            "type": "string",
            "label": "Pixel ID",
            "description": "The numeric ID of the Meta Pixel / dataset that should receive these events (e.g. `123451234512345`). Find it in Meta Events Manager → Data sources → your Pixel → Settings. If you have already set up a Pixel for your website, reuse the same Pixel ID for browser and server events so Meta can deduplicate them.",
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
            "key": "eventId",
            "type": "string",
            "label": "Event ID",
            "description": "The ID of the event.",
            "default": "{event.uuid}",
            "secret": False,
            "required": True,
        },
        {
            "key": "eventSourceUrl",
            "type": "string",
            "label": "Event source URL",
            "description": "The URL of the page where the event occurred.",
            "default": "{event.properties.$current_url}",
            "secret": False,
            "required": False,
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
            "description": "Where the conversion happened. For most web installations this is `website`. See the full list at https://developers.facebook.com/docs/marketing-api/conversions-api/parameters/server-event#action-source.",
            "default": "website",
            "secret": False,
            "required": True,
        },
        {
            "key": "userData",
            "type": "dictionary",
            "label": "User data",
            "description": "Customer information used by Meta for event matching. PII values (email, name) must be SHA-256 hashed and lowercased — the defaults below already do this. See https://developers.facebook.com/docs/marketing-api/conversions-api/parameters/customer-information-parameters for the full list of supported keys.",
            "default": {
                "em": "{sha256Hex(lower(person.properties.email))}",
                "fn": "{sha256Hex(lower(person.properties.first_name))}",
                "ln": "{sha256Hex(lower(person.properties.last_name))}",
                "fbc": "{not empty(person.properties.fbclid ?? person.properties.$initial_fbclid) ? f'fb.1.{toUnixTimestampMilli(now())}.{person.properties.fbclid ?? person.properties.$initial_fbclid}' : ''}",
                "client_user_agent": "{event.properties.$raw_user_agent}",
            },
            "secret": False,
            "required": True,
        },
        {
            "key": "customData",
            "type": "dictionary",
            "label": "Custom data",
            "description": "A map of object properties that describe the conversion. Empty values are dropped before sending. See https://developers.facebook.com/docs/marketing-api/conversions-api/parameters/custom-data for the full reference of supported keys.",
            "default": {
                "currency": "{event.properties.currency ?? 'USD'}",
                "value": "{toFloat(event.properties.value ?? event.properties.revenue ?? event.properties.price)}",
                "content_ids": "{event.properties.content_ids ?? (event.properties.product_id ? [event.properties.product_id] : null)}",
                "content_type": "{event.properties.content_type}",
                "content_name": "{event.properties.content_name ?? event.properties.product_name ?? event.properties.name}",
                "content_category": "{event.properties.content_category ?? event.properties.category}",
                "contents": "{event.properties.contents}",
                "order_id": "{event.properties.order_id ?? event.properties.transaction_id}",
                "num_items": "{event.properties.num_items ?? event.properties.quantity}",
                "search_string": "{event.properties.search_string ?? event.properties.query}",
                "predicted_ltv": "{event.properties.predicted_ltv}",
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
