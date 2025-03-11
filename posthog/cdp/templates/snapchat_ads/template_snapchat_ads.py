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
    {
        "key": "testEventMode",
        "type": "boolean",
        "label": "Test Event Mode",
        "description": "Use this field to specify that events should be test events rather than actual traffic. You'll want to disable this field when sending real traffic through this integration.",
        "default": False,
        "secret": False,
        "required": False,
    },
]

template: HogFunctionTemplate = HogFunctionTemplate(
    status="beta",
    free=False,
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

if (not (not empty(body.data.1.user_data.em) or not empty(body.data.1.user_data.ph) or ( not empty(body.data.1.user_data.client_ip_address) and not empty(body.data.1.user_data.client_user_agent) ))) {
    return
}

let res := fetch(f'https://tr.snapchat.com/v3/{inputs.pixelId}/events{inputs.testEventMode ? '/validate' : ''}?access_token={inputs.oauth.access_token}', {
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
                "em": "{sha256Hex(lower(person.properties.email))}",
                "ph": "{sha256Hex(person.properties.phone)}",
                "sc_click_id": "{person.properties.sccid ?? person.properties.$initial_sccid}",
                "client_user_agent": "{event.properties.$raw_user_agent}",
                "fn": "{sha256Hex(lower(person.properties.first_name))}",
                "ln": "{sha256Hex(lower(person.properties.last_name))}",
                "client_ip_address": "{event.properties.$ip}",
                "external_id": "{sha256Hex(person.id)}",
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
            ": event.event == 'Order Completed' ? 'PURCHASE'"
            ": event.event == 'Checkout Started' ? 'START_CHECKOUT'"
            ": event.event == 'Product Added' ? 'ADD_CART'"
            ": event.event == 'Payment Info Entered' ? 'ADD_BILLING'"
            ": event.event == 'Promotion Clicked' ? 'AD_CLICK'"
            ": event.event == 'Promotion Viewed' ? 'AD_VIEW'"
            ": event.event == 'Product Added to Wishlist' ? 'ADD_TO_WISHLIST'"
            ": event.event == 'Product Viewed' ? 'VIEW_CONTENT'"
            ": event.event == 'Product List Viewed' ? 'VIEW_CONTENT'"
            ": event.event == 'Products Searched' ? 'SEARCH'"
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
    #         name="Order Completed",
    #         include_by_default=True,
    #         filters={"events": [{"id": "Order Completed", "type": "events"}]},
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
    #         name="Checkout Started",
    #         include_by_default=True,
    #         filters={"events": [{"id": "Checkout Started", "type": "events"}]},
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
    #         name="Product Added",
    #         include_by_default=True,
    #         filters={"events": [{"id": "Product Added", "type": "events"}]},
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
    #         name="Payment Info Entered",
    #         include_by_default=True,
    #         filters={"events": [{"id": "Payment Info Entered", "type": "events"}]},
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
    #         name="Promotion Clicked",
    #         include_by_default=True,
    #         filters={"events": [{"id": "Promotion Clicked", "type": "events"}]},
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
    #         name="Promotion Viewed",
    #         include_by_default=True,
    #         filters={"events": [{"id": "Promotion Viewed", "type": "events"}]},
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
    #         name="Product Added to Wishlist",
    #         include_by_default=True,
    #         filters={"events": [{"id": "Product Added to Wishlist", "type": "events"}]},
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
    #         name="Product Viewed",
    #         include_by_default=True,
    #         filters={"events": [{"id": "Product Viewed", "type": "events"}]},
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
    #         name="Product List Viewed",
    #         include_by_default=True,
    #         filters={"events": [{"id": "Product List Viewed", "type": "events"}]},
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
    #         name="Products Searched",
    #         include_by_default=True,
    #         filters={"events": [{"id": "Products Searched", "type": "events"}]},
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
            {"id": "Order Completed", "type": "events"},
            {"id": "Checkout Started", "type": "events"},
            {"id": "Product Added", "type": "events"},
            {"id": "Payment Info Entered", "type": "events"},
            {"id": "Promotion Clicked", "type": "events"},
            {"id": "Promotion Viewed", "type": "events"},
            {"id": "Product Added to Wishlist", "type": "events"},
            {"id": "Product Viewed", "type": "events"},
            {"id": "Product List Viewed", "type": "events"},
            {"id": "Products Searched", "type": "events"},
        ],
        "actions": [],
        "filter_test_accounts": True,
    },
)
