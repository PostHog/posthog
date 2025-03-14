from posthog.cdp.templates.hog_function_template import HogFunctionTemplate

template: HogFunctionTemplate = HogFunctionTemplate(
    status="beta",
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
            'event_time': inputs.eventTimestamp,
            'event_id': inputs.eventId,
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
    if (not empty(value)) {
        body.data.1.user[key] := value
    }
}

for (let key, value in inputs.propertyProperties) {
    if (not empty(value)) {
        body.data.1.properties[key] := value
    }
}

for (let key, value in inputs.pageProperties) {
    if (not empty(value)) {
        body.data.1.page[key] := value
    }
}

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
            "default": "{"
            "event.event == 'Payment Info Entered' ? 'AddPaymentInfo'"
            ": event.event == 'Product Added' ? 'AddToCart'"
            ": event.event == 'Product Added to Wishlist' ? 'AddToWishlist'"
            ": event.event == 'Product Clicked' ? 'ClickButton'"
            ": event.event == 'Order Completed' ? 'CompletePayment'"
            ": event.event == 'Signed Up' ? 'CompleteRegistration'"
            ": event.event == 'Checkout Started' ? 'InitiateCheckout'"
            ": event.event == 'Order Completed' ? 'PlaceAnOrder'"
            ": event.event == 'Products Searched' ? 'Search'"
            ": event.event == 'Product Viewed' ? 'ViewContent'"
            ": event.event"
            "}",
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
            "key": "eventTimestamp",
            "type": "string",
            "label": "Event timestamp",
            "description": "A Unix timestamp in seconds indicating when the actual event occurred. You must send this date in GMT time zone.",
            "default": "{toUnixTimestamp(event.timestamp)}",
            "secret": False,
            "required": True,
        },
        {
            "key": "userProperties",
            "type": "dictionary",
            "label": "User properties",
            "description": "A map that contains customer information data. See this page for options: https://business-api.tiktok.com/portal/docs?id=1771101151059969#item-link-user%20parameters",
            "default": {
                "email": "{sha256Hex(lower(person.properties.email))}",
                "ttclid": "{person.properties.ttclid ?? person.properties.$initial_ttclid}",
                "phone": "{sha256Hex(person.properties.phone)}",
                "external_id": "{sha256Hex(person.id)}",
                "ip": "{event.properties.$ip}",
                "user_agent": "{event.properties.$raw_user_agent}",
                "first_name": "{sha256Hex(lower(person.properties.first_name))}",
                "last_name": "{sha256Hex(lower(person.properties.last_name))}",
            },
            "secret": False,
            "required": True,
        },
        {
            "key": "propertyProperties",
            "type": "dictionary",
            "label": "Property properties",
            "description": "A map that contains customer information data. See this page for options: https://business-api.tiktok.com/portal/docs?id=1771101151059969#item-link-properties%20parameters",
            "default": {
                "content_ids": "{event.event in ('Order Completed', 'Checkout Started') ? arrayMap(x -> x.sku, event.properties.products ?? []) : [event.properties.sku]}",
                "contents": "{event.event in ('Order Completed', 'Checkout Started') ? arrayMap(x -> ({'price': x.price, 'content_id': x.sku, 'content_category': x.category, 'content_name': x.name, 'brand': x.brand}), event.properties.products ?? []) : [{'price': event.properties.price, 'content_id': event.properties.sku, 'content_category': event.properties.category, 'content_name': event.properties.name, 'brand': event.properties.brand}]}",
                "content_type": "product",
                "currency": "{event.properties.currency ?? 'USD'}",
                "value": "{toFloat(event.properties.value ?? event.properties.revenue ?? event.properties.price)}",
                "num_items": "{event.event in ('Order Completed', 'Checkout Started') ? length(arrayMap(x -> x.sku, event.properties.products ?? [])) : event.properties.quantity}",
                "search_string": "{event.properties.query}",
                "description": "",
                "order_id": "{event.properties.order_id}",
                "shop_id": "{event.properties.shop_id}",
            },
            "secret": False,
            "required": True,
        },
        {
            "key": "pageProperties",
            "type": "dictionary",
            "label": "Page properties",
            "description": "A map that contains page information data. See this page for options: https://business-api.tiktok.com/portal/docs?id=1771101151059969#item-link-page%20parameters",
            "default": {
                "referrer": "{event.properties.$referrer}",
                "url": "{event.properties.$current_url}",
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
        "events": [
            {"id": "Payment Info Entered", "type": "events"},
            {"id": "Product Added", "type": "events"},
            {"id": "Product Added to Wishlist", "type": "events"},
            {"id": "Product Clicked", "type": "events"},
            {"id": "Order Completed", "type": "events"},
            {"id": "Signed Up", "type": "events"},
            {"id": "Checkout Started", "type": "events"},
            {"id": "Order Completed", "type": "events"},
            {"id": "Products Searched", "type": "events"},
            {"id": "Product Viewed", "type": "events"},
        ],
        "actions": [],
        "filter_test_accounts": True,
    },
)
