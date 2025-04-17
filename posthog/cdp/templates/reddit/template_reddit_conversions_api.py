from posthog.cdp.templates.hog_function_template import HogFunctionTemplate

common_inputs = [
    {
        "key": "eventProperties",
        "type": "dictionary",
        "description": "Map of Reddit event attributes and their values. Check out these pages for more details: https://business.reddithelp.com/s/article/manual-conversion-events-with-the-reddit-pixel and https://business.reddithelp.com/s/article/about-event-metadata",
        "label": "Event parameters",
        "default": {
            "conversion_id": "{event.uuid}",
            "products": "{event.properties.products ? arrayMap(product -> ({'id': product.product_id, 'category': product.category, 'name': product.name}), event.properties.products) : event.properties.product_id ? [{'id': event.properties.product_id, 'category': event.properties.category, 'name': event.properties.name}] : null}",
            "value": "{toFloat(event.properties.value ?? event.properties.revenue ?? event.properties.price)}",
            "currency": "{event.properties.currency}",
        },
        "secret": False,
        "required": False,
    },
]

template_reddit_conversions_api: HogFunctionTemplate = HogFunctionTemplate(
    free=False,
    status="beta",  # due to rate limiting on the API, we will need the CDP to implement event batching before releasing this to users with more than 10 events/second, see https://ads-api.reddit.com/docs/v2/#section/Best-practices
    type="destination",
    id="template-reddit-conversions-api",
    name="Reddit Conversions API",
    description="Track how many Reddit users interact with your website.",
    icon_url="/static/services/reddit.png",
    category=["Advertisement"],
    hog="""
let RDT_ALLOWED_EVENT_NAMES := [
    'PageVisit',
    'Search',
    'AddToCart',
    'AddToWishlist',
    'Purchase',
    'ViewContent',
    'Lead',
    'SignUp',
    'Custom',
];

let eventProperties := {};
for (let key, value in inputs.eventProperties) {
    if (not empty(value)) {
        eventProperties[key] := value;
    }
}

let userProperties := {};
for (let key, value in inputs.userProperties) {
    if (not empty(value)) {
        userProperties[key] := value;
    }
}

let eventType := {'tracking_type': inputs.eventType};
if (not has(RDT_ALLOWED_EVENT_NAMES, inputs.eventType)) {
    eventType.tracking_type := 'Custom';
    eventType.custom_event_name := inputs.eventType;
}

let eventData := {
    'event_at': event.timestamp,
    'event_type': eventType,
    'user': userProperties,
    'event_metadata': eventProperties,
};

let events := [eventData];

let body := {
    'test_mode': false,
    'events': events,
};

let url := f'https://ads-api.reddit.com/api/v2.0/conversions/events/{inputs.accountId}';
let userAgent := 'hog:com.posthog.cdp:0.0.1 (by /u/PostHogTeam)';
let headers := {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {inputs.conversionsAccessToken}',
        'User-Agent': userAgent,
    };

let res := fetch(url, {
    'method': 'POST',
    'headers': headers,
    'body': body,
});
if (res.status >= 400) {
    throw Error(f'Error from https://ads-api.reddit.com (status {res.status}): {res.body}')
}
""".strip(),
    inputs_schema=[
        {
            "key": "accountId",
            "type": "string",
            "label": "Reddit Ads account ID",
            "description": "The ID of the Reddit Ads account that the conversion event belongs to. Your account ID may or may not contain the t2_ prefix.",  # this is copied verbatim from https://ads-api.reddit.com/docs/v2/#section/Best-practices
            "default": "",
            "secret": False,
            "required": True,
        },
        {
            "key": "conversionsAccessToken",
            "type": "string",
            "label": "Conversion Access Token",
            "description": "You must obtain a Conversion Access Token.",
            "default": "",
            "secret": True,
            "required": True,
        },
        {
            "key": "userProperties",
            "type": "dictionary",
            "description": "Map of Reddit user parameters and their values. Check out this page for more details: https://business.reddithelp.com/s/article/manual-conversion-events-with-the-reddit-pixel",
            "label": "User parameters",
            "default": {
                "email": "{person.properties.email}",
                "screen_dimensions": "{{'width': person.properties.$screen_width, 'height': person.properties.$screen_height}}",
                "user_agent": "{person.properties.$raw_user_agent}",
                "ip": "{sha256Hex(event.properties.$ip)}",  # use event properties here, as $ip is not a person property
            },
            "secret": False,
            "required": False,
        },
        {
            "key": "eventType",
            "type": "string",
            "label": "Event Type",
            "description": "Check out this page for possible event types: https://business.reddithelp.com/s/article/manual-conversion-events-with-the-reddit-pixel",
            "default": "{"
            "event.event == '$pageview' ? 'PageVisit'"
            ": event.event == 'Products Searched' ? 'Search'"
            ": event.event == 'Product Added' ? 'AddToCart'"
            ": event.event == 'Product Added to Wishlist' ? 'AddToWishlist'"
            ": event.event == 'Order Completed' ? 'Purchase'"
            ": event.event == 'Product Viewed' ? 'ViewContent'"
            ": event.event == 'Lead Generated' ? 'Lead'"
            ": event.event == 'Signed Up' ? 'SignUp'"
            ": event.event"
            "}",
            "required": True,
        },
        *common_inputs,
    ],
    filters={
        "events": [
            {"id": "$pageview", "name": "Pageview", "type": "events"},
            {"id": "Products Searched", "name": "Products Searched", "type": "events"},
            {"id": "Product Added", "name": "Product Added", "type": "events"},
            {"id": "Product Added to Wishlist", "name": "Product Added to Wishlist", "type": "events"},
            {"id": "Order Completed", "name": "Order Completed", "type": "events"},
            {"id": "Product Viewed", "name": "Product Viewed", "type": "events"},
            {"id": "Lead Generated", "name": "Lead Generated", "type": "events"},
            {"id": "Signed Up", "name": "Signed Up", "type": "events"},
        ],
        "actions": [],
        "filter_test_accounts": True,
    },
    # See our event specification here:
    # https://posthog.com/docs/data/event-spec/ecommerce-events
    # And reddit's here:
    # https://business.reddithelp.com/s/article/manual-conversion-events-with-the-reddit-pixel
    # mapping_templates=[
    #     HogFunctionMappingTemplate(
    #         name="Page Visit",
    #         include_by_default=True,
    #         filters={"events": [{"id": "$pageview", "name": "Pageview", "type": "events"}]},
    #         inputs_schema=[
    #             {
    #                 "key": "eventType",
    #                 "type": "string",
    #                 "label": "Event Type",
    #                 "description": "Check out this page for possible event types: https://business.reddithelp.com/s/article/manual-conversion-events-with-the-reddit-pixel",
    #                 "default": "PageVisit",
    #                 "required": True,
    #             },
    #             *common_inputs,
    #         ],
    #     ),
    #     HogFunctionMappingTemplate(
    #         name="Search",
    #         include_by_default=True,
    #         filters={"events": [{"id": "Products Searched", "name": "Products Searched", "type": "events"}]},
    #         inputs_schema=[
    #             {
    #                 "key": "eventType",
    #                 "type": "string",
    #                 "label": "Event Type",
    #                 "description": "Check out this page for possible event types: https://business.reddithelp.com/s/article/manual-conversion-events-with-the-reddit-pixel",
    #                 "default": "Search",
    #                 "required": True,
    #             },
    #             *common_inputs,
    #         ],
    #     ),
    #     HogFunctionMappingTemplate(
    #         name="Product Added",
    #         include_by_default=True,
    #         filters={"events": [{"id": "Product Added", "name": "Product Added", "type": "events"}]},
    #         inputs_schema=[
    #             {
    #                 "key": "eventType",
    #                 "type": "string",
    #                 "label": "Event Type",
    #                 "description": "Check out this page for possible event types: https://business.reddithelp.com/s/article/manual-conversion-events-with-the-reddit-pixel",
    #                 "default": "AddToCart",
    #                 "required": True,
    #             },
    #             *common_inputs,
    #         ],
    #     ),
    #     HogFunctionMappingTemplate(
    #         name="Product Added to Wishlist",
    #         include_by_default=True,
    #         filters={
    #             "events": [{"id": "Product Added to Wishlist", "name": "Product Added to Wishlist", "type": "events"}]
    #         },
    #         inputs_schema=[
    #             {
    #                 "key": "eventType",
    #                 "type": "string",
    #                 "label": "Event Type",
    #                 "description": "Check out this page for possible event types: https://business.reddithelp.com/s/article/manual-conversion-events-with-the-reddit-pixel",
    #                 "default": "AddToWishlist",
    #                 "required": True,
    #             },
    #             *common_inputs,
    #         ],
    #     ),
    #     HogFunctionMappingTemplate(
    #         name="Order Completed",
    #         include_by_default=True,
    #         filters={"events": [{"id": "Order Completed", "name": "Order Completed", "type": "events"}]},
    #         inputs_schema=[
    #             {
    #                 "key": "eventType",
    #                 "type": "string",
    #                 "label": "Event Type",
    #                 "description": "Check out this page for possible event types: https://business.reddithelp.com/s/article/manual-conversion-events-with-the-reddit-pixel",
    #                 "default": "Purchase",
    #                 "required": True,
    #             },
    #             *common_inputs,
    #         ],
    #     ),
    #     HogFunctionMappingTemplate(
    #         name="Product Viewed",
    #         include_by_default=True,
    #         filters={"events": [{"id": "Product Viewed", "name": "Product Viewed", "type": "events"}]},
    #         inputs_schema=[
    #             {
    #                 "key": "eventType",
    #                 "type": "string",
    #                 "label": "Event Type",
    #                 "description": "Check out this page for possible event types: https://business.reddithelp.com/s/article/manual-conversion-events-with-the-reddit-pixel",
    #                 "default": "ViewContent",
    #                 "required": True,
    #             },
    #             *common_inputs,
    #         ],
    #     ),
    #     HogFunctionMappingTemplate(
    #         name="Lead Generated",
    #         include_by_default=True,
    #         filters={"events": [{"id": "Lead Generated", "name": "Lead Generated", "type": "events"}]},
    #         inputs_schema=[
    #             {
    #                 "key": "eventType",
    #                 "type": "string",
    #                 "label": "Event Type",
    #                 "description": "Check out this page for possible event types: https://business.reddithelp.com/s/article/manual-conversion-events-with-the-reddit-pixel",
    #                 "default": "Lead",
    #                 "required": True,
    #             },
    #             *common_inputs,
    #         ],
    #     ),
    #     HogFunctionMappingTemplate(
    #         name="Signed Up",
    #         include_by_default=True,
    #         filters={"events": [{"id": "Signed Up", "name": "Signed Up", "type": "events"}]},
    #         inputs_schema=[
    #             {
    #                 "key": "eventType",
    #                 "type": "string",
    #                 "label": "Event Type",
    #                 "description": "Check out this page for possible event types: https://business.reddithelp.com/s/article/manual-conversion-events-with-the-reddit-pixel",
    #                 "default": "SignUp",
    #                 "required": True,
    #             },
    #             *common_inputs,
    #         ],
    #     ),
    # ],
)
