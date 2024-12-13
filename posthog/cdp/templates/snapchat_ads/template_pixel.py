from posthog.cdp.templates.hog_function_template import HogFunctionMappingTemplate, HogFunctionTemplate

template_snapchat_pixel: HogFunctionTemplate = HogFunctionTemplate(
    status="client-side",
    type="site_destination",
    id="template-snapchat-pixel",
    name="Snapchat Pixel",
    description="Track how many Snapchat users interact with your website.",
    icon_url="/static/services/snapchat.png",
    category=["Advertisement"],
    hog="""
// Adds window.snaptr and lazily loads the Snapchat Pixel script
function initSnippet() {
    console.log('SNAP: initSnippet');
    (function(e,t,n){if(e.snaptr)return;var a=e.snaptr=function()
    {a.handleRequest?a.handleRequest.apply(a,arguments):a.queue.push(arguments)};
    a.queue=[];var s='script';r=t.createElement(s);r.async=!0;
    r.src=n;var u=t.getElementsByTagName(s)[0];
    u.parentNode.insertBefore(r,u);})(window,document,
    'https://sc-static.net/scevent.min.js');
}

export function onLoad({ inputs }) {
    initSnippet();
    console.log('SNAP: onLoad');
    let userProperties = {};
    for (const [key, value] of Object.entries(inputs.userProperties)) {
        if (value) {
            userProperties[key] = value;
        }
    };
    console.log('SNAP: onLoad/end', userProperties);
    snaptr('init', inputs.pixelId, userProperties);
}
export function onEvent({ inputs }) {
    console.log('SNAP: onEvent');
    let eventProperties = {};
    for (const [key, value] of Object.entries(inputs.eventProperties)) {
        if (value) {
            eventProperties[key] = value;
        }
    };
    for (const [key, value] of Object.entries(inputs.additionalProperties)) {
        if (value) {
            eventProperties[key] = value;
        }
    };
    console.log('SNAP: onEvent/end', eventProperties);
    snaptr('track', 'PAGE_VIEW', eventProperties);
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
            },
            "secret": False,
            "required": False,
        },
        {
            "key": "eventProperties",
            "type": "dictionary",
            "description": "Map of Snapchat event attributes and their values. Check out this page for more details: https://businesshelp.snapchat.com/s/article/pixel-direct-implementation",
            "label": "Event parameters",
            "default": {
                "price": "{toFloat(event.properties.price or event.properties.value or event.properties.revenue)}",
                "currency": "{event.properties.currency}",
                "item_category": "{event.properties.category}",
                "description": "{event.properties.description}",
                "search_string": "{event.properties.search_string}",
                "number_items": "{toInt(event.properties.number_items or event.properties.quantity)}",
                "payment_info_available": "{toInt(event.properties.payment_info_available)}",
                "sign_up_method": "{event.properties.sign_up_method}",
                "success": "{toInt(event.properties.success) in (0, 1) ? toInt(event.properties.success) : null}",
                "payment_info_available": "{toInt(event.properties.payment_info_available) in (0, 1) ? toInt(event.properties.payment_info_available) : null}",
                "client_deduplication_id": "{event.uuid}",
            },
            "secret": False,
            "required": False,
        },
        {
            "key": "itemIds",
            "type": "string",
            "label": "Item IDs",
            "description": "Array of item IDs, for events that require it.",
            "default": "{event.properties.item_ids}",
            "required": True,
        },
        {
            "key": "transactionId",
            "type": "string",
            "label": "Transaction ID",
            "description": "Unique key for this transaction, for events that require it",
            "default": "{event.properties.orderId ?? event.properties.transactionId ?? event.properties.transaction_id ?? event.uuid}",
            "required": True,
        },
    ],
    mapping_templates=[
        HogFunctionMappingTemplate(
            name="Order completed",
            include_by_default=True,
            filters={"events": [{"id": "Order completed", "type": "events"}]},
            inputs_schema=[
                {
                    "key": "additionalProperties",
                    "type": "dictionary",
                    "description": "Additional properties to add for this event type",
                    "label": "Additional parameters",
                    "default": {
                        "item_ids": "{inputs.itemIds}",
                        "transaction_id": "{inputs.transactionId}",
                    },
                },
            ],
        ),
        HogFunctionMappingTemplate(
            name="Checkout started",
            filters={"events": [{"id": "Checkout started", "type": "events"}]},
            inputs_schema=[
                {
                    "key": "additionalProperties",
                    "type": "dictionary",
                    "description": "Additional properties to add for this event type",
                    "label": "Additional parameters",
                    "default": {
                        "item_ids": "{inputs.itemIds}",
                        "transaction_id": "{inputs.transactionId}",
                    },
                },
            ],
        ),
        HogFunctionMappingTemplate(
            name="Product added",
            filters={"events": [{"id": "Product added", "type": "events"}]},
            inputs_schema=[
                {
                    "key": "additionalProperties",
                    "type": "dictionary",
                    "description": "Additional properties to add for this event type",
                    "label": "Additional parameters",
                    "default": {
                        "item_ids": "{inputs.itemIds}",
                    },
                },
            ],
        ),
        HogFunctionMappingTemplate(
            name="Payment info entered",
            filters={"events": [{"id": "Payment info entered", "type": "events"}]},
            inputs_schema=[
                {
                    "key": "additionalProperties",
                    "type": "dictionary",
                    "description": "Additional properties to add for this event type",
                    "label": "Additional parameters",
                    "default": {
                        "item_ids": "{inputs.itemIds}",
                        "transaction_id": "{inputs.transactionId}",
                    },
                },
            ],
        ),
        HogFunctionMappingTemplate(
            name="Promotion clicked",
            filters={"events": [{"id": "Promotion clicked", "type": "events"}]},
            inputs_schema=[
                {
                    "key": "additionalProperties",
                    "type": "dictionary",
                    "description": "Additional properties to add for this event type",
                    "label": "Additional parameters",
                    "default": {
                        "item_ids": "{inputs.itemIds}",
                    },
                },
            ],
        ),
        HogFunctionMappingTemplate(
            name="Promotion viewed",
            filters={"events": [{"id": "Promotion viewed", "type": "events"}]},
            inputs_schema=[
                {
                    "key": "additionalProperties",
                    "type": "dictionary",
                    "description": "Additional properties to add for this event type",
                    "label": "Additional parameters",
                    "default": {
                        "item_ids": "{inputs.itemIds}",
                    },
                },
            ],
        ),
        HogFunctionMappingTemplate(
            name="Product added to wishlist",
            filters={"events": [{"id": "Product added to wishlist", "type": "events"}]},
            inputs_schema=[
                {
                    "key": "additionalProperties",
                    "type": "dictionary",
                    "description": "Additional properties to add for this event type",
                    "label": "Additional parameters",
                    "default": {
                        "item_ids": "{inputs.itemIds}",
                    },
                },
            ],
        ),
        HogFunctionMappingTemplate(
            name="Product viewed",
            filters={"events": [{"id": "Product viewed", "type": "events"}]},
            inputs_schema=[
                {
                    "key": "additionalProperties",
                    "type": "dictionary",
                    "description": "Additional properties to add for this event type",
                    "label": "Additional parameters",
                    "default": {
                        "item_ids": "{inputs.itemIds}",
                    },
                },
            ],
        ),
        HogFunctionMappingTemplate(
            name="Product list viewed",
            filters={"events": [{"id": "Product list viewed", "type": "events"}]},
            inputs_schema=[
                {
                    "key": "additionalProperties",
                    "type": "dictionary",
                    "description": "Additional properties to add for this event type",
                    "label": "Additional parameters",
                    "default": {
                        "item_ids": "{inputs.itemIds}",
                    },
                },
            ],
        ),
        HogFunctionMappingTemplate(
            name="Products searched",
            filters={"events": [{"id": "Products searched", "type": "events"}]},
            inputs_schema=[
                {
                    "key": "additionalProperties",
                    "type": "dictionary",
                    "description": "Additional properties to add for this event type",
                    "label": "Additional parameters",
                    "default": {
                        "item_ids": "{inputs.itemIds}",
                        "search_string": "{event.properties.query}",
                    },
                },
            ],
        ),
    ],
)
