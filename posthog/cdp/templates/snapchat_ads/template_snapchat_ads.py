from posthog.cdp.templates.hog_function_template import HogFunctionTemplate

common_inputs = [
    {
        "key": "eventId",
        "type": "string",
        "label": "Event ID",
        "description": "This field represents a unique identifier chosen to represent an event",
        "default": "{event.uuid}",
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
        "key": "eventSourceUrl",
        "type": "string",
        "label": "Event source URL",
        "description": "The URL of the web page where the event took place.",
        "default": "{event.properties.$current_url}",
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
        "default": "WEB",
        "secret": False,
        "required": True,
    },
    {
        "key": "customData",
        "type": "dictionary",
        "label": "Custom data",
        "description": "A map that contains custom data. See this page for options: https://developers.snap.com/api/marketing-api/Conversions-API/Parameters#custom-data-parameters",
        "default": {
            "value": "{toFloat(event.properties.price ?? event.properties.value ?? event.properties.revenue)}",
            "currency": "{event.properties.currency}",
            "content_ids": "{event.properties.item_ids}",
            "content_category": "{event.properties.category}",
            "search_string": "{event.properties.search_string ?? event.properties.query}",
            "num_items": "{toInt(event.properties.number_items ?? event.properties.quantity)}",
            "order_id": "{event.properties.orderId ?? event.properties.transactionId ?? event.properties.transaction_id}",
            "event_id": "{event.uuid}",
        },
        "secret": False,
        "required": True,
    },
]

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
            'event_name': inputs.eventType,
            'action_source': inputs.actionSource,
            'event_time': inputs.eventTime,
            'event_source_url': inputs.eventSourceUrl,
            'user_data': {},
            'custom_data': {}
        }
    ]
}

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

let res := fetch(f'https://tr.snapchat.com/v3/{inputs.pixelId}/events?access_token={inputs.oauth.access_token}', {
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
            "key": "oauth",
            "type": "integration",
            "integration": "snapchat",
            "label": "Snapchat account",
            "requiredScopes": "snapchat-offline-conversions-api snapchat-marketing-api",
            "secret": False,
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
            "key": "userData",
            "type": "dictionary",
            "label": "User data",
            "description": "A map that contains customer information data. See this page for options: https://developers.snap.com/api/marketing-api/Conversions-API/Parameters#user-data-parameters",
            "default": {
                "em": "{sha256Hex(person.properties.email)}",
                "ph": "{sha256Hex(person.properties.phone)}",
                "sc_click_id": "{person.properties.sccid ?? person.properties.$initial_sccid}",
            },
            "secret": False,
            "required": True,
        },
        {
            "key": "eventType",
            "type": "string",
            "label": "Event Type",
            "description": "Check out this page for possible event types: https://businesshelp.snapchat.com/s/article/pixel-direct-implementation",
            "default": "{"
            "event.event == '$pageview' ? 'PAGE_VIEW'"
            ": event.event == 'Order completed' ? 'PURCHASE'"
            ": event.event == 'Checkout started' ? 'START_CHECKOUT'"
            ": event.event == 'Product added' ? 'ADD_CART'"
            ": event.event == 'Payment info entered' ? 'ADD_BILLING'"
            ": event.event == 'Promotion clicked' ? 'AD_CLICK'"
            ": event.event == 'Promotion viewed' ? 'AD_VIEW'"
            ": event.event == 'Product added to wishlist' ? 'ADD_TO_WISHLIST'"
            ": event.event == 'Product viewed' ? 'VIEW_CONTENT'"
            ": event.event == 'Product list viewed' ? 'VIEW_CONTENT'"
            ": event.event == 'Products searched' ? 'SEARCH'"
            ": event.event"
            "}",
            "required": True,
        },
        *common_inputs,
    ],
    # mapping_templates=[
    #     HogFunctionMappingTemplate(
    #         name="Page viewed",
    #         include_by_default=True,
    #         filters={"events": [{"id": "$pageview", "name": "Pageview", "type": "events"}]},
    #         inputs_schema=[
    #             {
    #                 "key": "eventType",
    #                 "type": "string",
    #                 "label": "Event Type",
    #                 "description": "Check out this page for possible event types: https://businesshelp.snapchat.com/s/article/pixel-direct-implementation",
    #                 "default": "PAGE_VIEW",
    #                 "required": True,
    #             },
    #             *common_inputs
    #         ],
    #     ),
    #     HogFunctionMappingTemplate(
    #         name="Order completed",
    #         include_by_default=True,
    #         filters={"events": [{"id": "Order completed", "type": "events"}]},
    #         inputs_schema=[
    #             {
    #                 "key": "eventType",
    #                 "type": "string",
    #                 "label": "Event Type",
    #                 "description": "Check out this page for possible event types: https://businesshelp.snapchat.com/s/article/pixel-direct-implementation",
    #                 "default": "PURCHASE",
    #                 "required": True,
    #             },
    #             *common_inputs
    #         ],
    #     ),
    #     HogFunctionMappingTemplate(
    #         name="Checkout started",
    #         include_by_default=True,
    #         filters={"events": [{"id": "Checkout started", "type": "events"}]},
    #         inputs_schema=[
    #             {
    #                 "key": "eventType",
    #                 "type": "string",
    #                 "label": "Event Type",
    #                 "description": "Check out this page for possible event types: https://businesshelp.snapchat.com/s/article/pixel-direct-implementation",
    #                 "default": "START_CHECKOUT",
    #                 "required": True,
    #             },
    #             *common_inputs
    #         ],
    #     ),
    #     HogFunctionMappingTemplate(
    #         name="Product added",
    #         include_by_default=True,
    #         filters={"events": [{"id": "Product added", "type": "events"}]},
    #         inputs_schema=[
    #             {
    #                 "key": "eventType",
    #                 "type": "string",
    #                 "label": "Event Type",
    #                 "description": "Check out this page for possible event types: https://businesshelp.snapchat.com/s/article/pixel-direct-implementation",
    #                 "default": "ADD_CART",
    #                 "required": True,
    #             },
    #             *common_inputs
    #         ],
    #     ),
    #     HogFunctionMappingTemplate(
    #         name="Payment info entered",
    #         include_by_default=True,
    #         filters={"events": [{"id": "Payment info entered", "type": "events"}]},
    #         inputs_schema=[
    #             {
    #                 "key": "eventType",
    #                 "type": "string",
    #                 "label": "Event Type",
    #                 "description": "Check out this page for possible event types: https://businesshelp.snapchat.com/s/article/pixel-direct-implementation",
    #                 "default": "ADD_BILLING",
    #                 "required": True,
    #             },
    #             *common_inputs
    #         ],
    #     ),
    #     HogFunctionMappingTemplate(
    #         name="Promotion clicked",
    #         include_by_default=True,
    #         filters={"events": [{"id": "Promotion clicked", "type": "events"}]},
    #         inputs_schema=[
    #             {
    #                 "key": "eventType",
    #                 "type": "string",
    #                 "label": "Event Type",
    #                 "description": "Check out this page for possible event types: https://businesshelp.snapchat.com/s/article/pixel-direct-implementation",
    #                 "default": "AD_CLICK",
    #                 "required": True,
    #             },
    #             *common_inputs
    #         ],
    #     ),
    #     HogFunctionMappingTemplate(
    #         name="Promotion viewed",
    #         include_by_default=True,
    #         filters={"events": [{"id": "Promotion viewed", "type": "events"}]},
    #         inputs_schema=[
    #             {
    #                 "key": "eventType",
    #                 "type": "string",
    #                 "label": "Event Type",
    #                 "description": "Check out this page for possible event types: https://businesshelp.snapchat.com/s/article/pixel-direct-implementation",
    #                 "default": "AD_VIEW",
    #                 "required": True,
    #             },
    #             *common_inputs
    #         ],
    #     ),
    #     HogFunctionMappingTemplate(
    #         name="Product added to wishlist",
    #         include_by_default=True,
    #         filters={"events": [{"id": "Product added to wishlist", "type": "events"}]},
    #         inputs_schema=[
    #             {
    #                 "key": "eventType",
    #                 "type": "string",
    #                 "label": "Event Type",
    #                 "description": "Check out this page for possible event types: https://businesshelp.snapchat.com/s/article/pixel-direct-implementation",
    #                 "default": "ADD_TO_WISHLIST",
    #                 "required": True,
    #             },
    #             *common_inputs
    #         ],
    #     ),
    #     HogFunctionMappingTemplate(
    #         name="Product viewed",
    #         include_by_default=True,
    #         filters={"events": [{"id": "Product viewed", "type": "events"}]},
    #         inputs_schema=[
    #             {
    #                 "key": "eventType",
    #                 "type": "string",
    #                 "label": "Event Type",
    #                 "description": "Check out this page for possible event types: https://businesshelp.snapchat.com/s/article/pixel-direct-implementation",
    #                 "default": "VIEW_CONTENT",
    #                 "required": True,
    #             },
    #             *common_inputs
    #         ],
    #     ),
    #     HogFunctionMappingTemplate(
    #         name="Product list viewed",
    #         include_by_default=True,
    #         filters={"events": [{"id": "Product list viewed", "type": "events"}]},
    #         inputs_schema=[
    #             {
    #                 "key": "eventType",
    #                 "type": "string",
    #                 "label": "Event Type",
    #                 "description": "Check out this page for possible event types: https://businesshelp.snapchat.com/s/article/pixel-direct-implementation",
    #                 "default": "VIEW_CONTENT",
    #                 "required": True,
    #             },
    #             *common_inputs
    #         ],
    #     ),
    #     HogFunctionMappingTemplate(
    #         name="Products searched",
    #         include_by_default=True,
    #         filters={"events": [{"id": "Products searched", "type": "events"}]},
    #         inputs_schema=[
    #             {
    #                 "key": "eventType",
    #                 "type": "string",
    #                 "label": "Event Type",
    #                 "description": "Check out this page for possible event types: https://businesshelp.snapchat.com/s/article/pixel-direct-implementation",
    #                 "default": "SEARCH",
    #                 "required": True,
    #             },
    #             *common_inputs
    #         ],
    #     ),
    # ],
    filters={
        "events": [
            {"id": "$pageview", "name": "Pageview", "type": "events"},
            {"id": "Order completed", "type": "events"},
            {"id": "Checkout started", "type": "events"},
            {"id": "Product added", "type": "events"},
            {"id": "Payment info entered", "type": "events"},
            {"id": "Promotion clicked", "type": "events"},
            {"id": "Promotion viewed", "type": "events"},
            {"id": "Product added to wishlist", "type": "events"},
            {"id": "Product viewed", "type": "events"},
            {"id": "Product list viewed", "type": "events"},
            {"id": "Products searched", "type": "events"},
        ],
        "actions": [],
        "filter_test_accounts": True,
    },
)
