from posthog.cdp.templates.hog_function_template import HogFunctionMappingTemplate, HogFunctionTemplate

common_inputs = [
    {
        "key": "eventProperties",
        "type": "dictionary",
        "description": "Map of Snapchat event attributes and their values. Check out this page for more details: https://businesshelp.snapchat.com/s/article/pixel-direct-implementation",
        "label": "Event parameters",
        "default": {
            "price": "{toFloat(event.properties.price ?? event.properties.value ?? event.properties.revenue)}",
            "currency": "{event.properties.currency}",
            "item_ids": "{event.properties.item_ids}",
            "item_category": "{event.properties.category}",
            "description": "{event.properties.description}",
            "search_string": "{event.properties.search_string}",
            "number_items": "{toInt(event.properties.number_items ?? event.properties.quantity)}",
            "payment_info_available": "{toInt(event.properties.payment_info_available)}",
            "sign_up_method": "{event.properties.sign_up_method}",
            "brands": "{event.properties.brands}",
            "success": "{toInt(event.properties.success) in (0, 1) ? toInt(event.properties.success) : null}",
            "transaction_id": "{event.properties.orderId ?? event.properties.transactionId ?? event.properties.transaction_id}",
            "client_dedup_id": "{event.uuid}",
        },
        "secret": False,
        "required": False,
    },
]

template_snapchat_pixel: HogFunctionTemplate = HogFunctionTemplate(
    status="beta",
    free=False,
    type="site_destination",
    id="template-snapchat-pixel",
    name="Snapchat Pixel",
    description="Track how many Snapchat users interact with your website. Note that this destination will set third-party cookies.",
    icon_url="/static/services/snapchat.png",
    category=["Advertisement"],
    hog="""
// Adds window.snaptr and lazily loads the Snapchat Pixel script
function initSnippet() {
    (function(e,t,n){if(e.snaptr)return;var a=e.snaptr=function()
    {a.handleRequest?a.handleRequest.apply(a,arguments):a.queue.push(arguments)};
    a.queue=[];var s='script';r=t.createElement(s);r.async=!0;
    r.src=n;var u=t.getElementsByTagName(s)[0];
    u.parentNode.insertBefore(r,u);})(window,document,
    'https://sc-static.net/scevent.min.js');
}

export function onLoad({ inputs }) {
    initSnippet();
    let userProperties = {};
    for (const [key, value] of Object.entries(inputs.userProperties)) {
        if (value) {
            userProperties[key] = value;
        }
    };
    if (posthog.config.debug) {
        console.log('[PostHog] snaptr init', inputs.pixelId, userProperties);
    }
    snaptr('init', inputs.pixelId, userProperties);
}
export function onEvent({ inputs }) {
    let eventProperties = {};
    for (const [key, value] of Object.entries(inputs.eventProperties)) {
        if (value) {
            eventProperties[key] = value;
        }
    };
    if (posthog.config.debug) {
        console.log('[PostHog] snaptr track', inputs.eventType, eventProperties);
    }
    snaptr('track', inputs.eventType, eventProperties);
}
""".strip(),
    inputs_schema=[
        {
            "key": "pixelId",
            "type": "string",
            "label": "Pixel ID",
            "description": "You must obtain a Pixel ID to use the Snapchat Pixel. If you've already set up a Pixel for your website, we recommend that you use the same Pixel ID for your browser and server events.",
            "default": "",
            "secret": False,
            "required": True,
        },
        {
            "key": "userProperties",
            "type": "dictionary",
            "description": "Map of Snapchat user parameters and their values. Check out this page for more details: https://businesshelp.snapchat.com/s/article/pixel-direct-implementation",
            "label": "User parameters",
            "default": {
                "user_email": "{person.properties.email}",
                "user_phone_number": "{person.properties.phone}",
            },
            "secret": False,
            "required": False,
        },
    ],
    mapping_templates=[
        HogFunctionMappingTemplate(
            name="Page Viewed",
            include_by_default=True,
            filters={"events": [{"id": "$pageview", "name": "Pageview", "type": "events"}]},
            inputs_schema=[
                {
                    "key": "eventType",
                    "type": "string",
                    "label": "Event Type",
                    "description": "Check out this page for possible event types: https://businesshelp.snapchat.com/s/article/pixel-direct-implementation",
                    "default": "PAGE_VIEW",
                    "required": True,
                },
                *common_inputs,
            ],
        ),
        HogFunctionMappingTemplate(
            name="Order Completed",
            include_by_default=True,
            filters={"events": [{"id": "Order Completed", "type": "events"}]},
            inputs_schema=[
                {
                    "key": "eventType",
                    "type": "string",
                    "label": "Event Type",
                    "description": "Check out this page for possible event types: https://businesshelp.snapchat.com/s/article/pixel-direct-implementation",
                    "default": "PURCHASE",
                    "required": True,
                },
                *common_inputs,
            ],
        ),
        HogFunctionMappingTemplate(
            name="Checkout Started",
            include_by_default=True,
            filters={"events": [{"id": "Checkout Started", "type": "events"}]},
            inputs_schema=[
                {
                    "key": "eventType",
                    "type": "string",
                    "label": "Event Type",
                    "description": "Check out this page for possible event types: https://businesshelp.snapchat.com/s/article/pixel-direct-implementation",
                    "default": "START_CHECKOUT",
                    "required": True,
                },
                *common_inputs,
            ],
        ),
        HogFunctionMappingTemplate(
            name="Product Added",
            include_by_default=True,
            filters={"events": [{"id": "Product Added", "type": "events"}]},
            inputs_schema=[
                {
                    "key": "eventType",
                    "type": "string",
                    "label": "Event Type",
                    "description": "Check out this page for possible event types: https://businesshelp.snapchat.com/s/article/pixel-direct-implementation",
                    "default": "ADD_CART",
                    "required": True,
                },
                *common_inputs,
            ],
        ),
        HogFunctionMappingTemplate(
            name="Payment Info Entered",
            include_by_default=True,
            filters={"events": [{"id": "Payment Info Entered", "type": "events"}]},
            inputs_schema=[
                {
                    "key": "eventType",
                    "type": "string",
                    "label": "Event Type",
                    "description": "Check out this page for possible event types: https://businesshelp.snapchat.com/s/article/pixel-direct-implementation",
                    "default": "ADD_BILLING",
                    "required": True,
                },
                *common_inputs,
            ],
        ),
        HogFunctionMappingTemplate(
            name="Promotion Clicked",
            include_by_default=True,
            filters={"events": [{"id": "Promotion Clicked", "type": "events"}]},
            inputs_schema=[
                {
                    "key": "eventType",
                    "type": "string",
                    "label": "Event Type",
                    "description": "Check out this page for possible event types: https://businesshelp.snapchat.com/s/article/pixel-direct-implementation",
                    "default": "AD_CLICK",
                    "required": True,
                },
                *common_inputs,
            ],
        ),
        HogFunctionMappingTemplate(
            name="Promotion Viewed",
            include_by_default=True,
            filters={"events": [{"id": "Promotion Viewed", "type": "events"}]},
            inputs_schema=[
                {
                    "key": "eventType",
                    "type": "string",
                    "label": "Event Type",
                    "description": "Check out this page for possible event types: https://businesshelp.snapchat.com/s/article/pixel-direct-implementation",
                    "default": "AD_VIEW",
                    "required": True,
                },
                *common_inputs,
            ],
        ),
        HogFunctionMappingTemplate(
            name="Product Added to Wishlist",
            include_by_default=True,
            filters={"events": [{"id": "Product Added to Wishlist", "type": "events"}]},
            inputs_schema=[
                {
                    "key": "eventType",
                    "type": "string",
                    "label": "Event Type",
                    "description": "Check out this page for possible event types: https://businesshelp.snapchat.com/s/article/pixel-direct-implementation",
                    "default": "ADD_TO_WISHLIST",
                    "required": True,
                },
                *common_inputs,
            ],
        ),
        HogFunctionMappingTemplate(
            name="Product Viewed",
            include_by_default=True,
            filters={"events": [{"id": "Product Viewed", "type": "events"}]},
            inputs_schema=[
                {
                    "key": "eventType",
                    "type": "string",
                    "label": "Event Type",
                    "description": "Check out this page for possible event types: https://businesshelp.snapchat.com/s/article/pixel-direct-implementation",
                    "default": "VIEW_CONTENT",
                    "required": True,
                },
                *common_inputs,
            ],
        ),
        HogFunctionMappingTemplate(
            name="Product List Viewed",
            include_by_default=True,
            filters={"events": [{"id": "Product List Viewed", "type": "events"}]},
            inputs_schema=[
                {
                    "key": "eventType",
                    "type": "string",
                    "label": "Event Type",
                    "description": "Check out this page for possible event types: https://businesshelp.snapchat.com/s/article/pixel-direct-implementation",
                    "default": "VIEW_CONTENT",
                    "required": True,
                },
                *common_inputs,
            ],
        ),
        HogFunctionMappingTemplate(
            name="Products Searched",
            include_by_default=True,
            filters={"events": [{"id": "Products Searched", "type": "events"}]},
            inputs_schema=[
                {
                    "key": "eventType",
                    "type": "string",
                    "label": "Event Type",
                    "description": "Check out this page for possible event types: https://businesshelp.snapchat.com/s/article/pixel-direct-implementation",
                    "default": "SEARCH",
                    "required": True,
                },
                *common_inputs,
            ],
        ),
    ],
)
