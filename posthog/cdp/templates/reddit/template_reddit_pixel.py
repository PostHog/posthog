from posthog.cdp.templates.hog_function_template import HogFunctionMappingTemplate, HogFunctionTemplate

common_inputs = [
    {
        "key": "eventProperties",
        "type": "dictionary",
        "description": "Map of Reddit event attributes and their values. Check out these pages for more details: https://business.reddithelp.com/s/article/manual-conversion-events-with-the-reddit-pixel and https://business.reddithelp.com/s/article/about-event-metadata",
        "label": "Event parameters",
        "default": {
            "conversion_id": "{event.uuid}",
            "products": "{event.properties.products ? arrayMap(product -> ({'id': product.product_id, 'category': product.category, 'name': product.name}), event.properties.products) : event.properties.product_id ? [{'id': event.properties.product_id, 'category': event.properties.category, 'name': event.properties.name}] : undefined}",
            "value": "{toFloat(event.properties.value ?? event.properties.revenue ?? event.properties.price)}",
            "currency": "{event.properties.currency}",
        },
        "secret": False,
        "required": False,
    },
]

template_reddit_pixel: HogFunctionTemplate = HogFunctionTemplate(
    free=False,
    status="alpha",
    type="site_destination",
    id="template-reddit-pixel",
    name="Reddit Pixel",
    description="Track how many Reddit users interact with your website. Note that this destination will set third-party cookies.",
    icon_url="/static/services/reddit.png",
    category=["Advertisement"],
    hog="""
// Adds window.rdt and lazily loads the Reddit Pixel script
function initSnippet() {
    !function(w,d){if(!w.rdt){var p=w.rdt=function(){p.sendEvent?p.sendEvent.apply(p,arguments):p.callQueue.push(arguments)};p.callQueue=[];var t=d.createElement("script");t.src="https://www.redditstatic.com/ads/pixel.js",t.async=!0;var s=d.getElementsByTagName("script")[0];s.parentNode.insertBefore(t,s)}}(window,document);
}

// These are the event names which we are allowed to call rdt with. If we want to send a different event name, we will
// need to use the 'Custom' event name, and pass original event name as 'customEventName' in event properties.
const RDT_ALLOWED_EVENT_NAMES = [
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

export function onLoad({ inputs, posthog }) {
    initSnippet();
    let userProperties = {};
    for (const [key, value] of Object.entries(inputs.userProperties)) {
        if (value) {
            userProperties[key] = value;
        }
    };
    if (posthog.config.debug) {
        console.log('[PostHog] rdt init', inputs.pixelId, userProperties);
    }
    rdt('init', inputs.pixelId, userProperties);
}
export function onEvent({ inputs, posthog }) {

    let eventProperties = {};
    for (const [key, value] of Object.entries(inputs.eventProperties)) {
        if (value) {
            eventProperties[key] = value;
        }
    };
    let eventName;
    if (RDT_ALLOWED_EVENT_NAMES.includes(inputs.eventType)) {
        eventName = inputs.eventType;
    } else {
        eventName = 'Custom';
        eventProperties.customEventName = inputs.eventType;
    }
    if (posthog.config.debug) {
        console.log('[PostHog] rdt track', eventName, eventProperties);
    }
    rdt('track', eventName, eventProperties);
}
""".strip(),
    inputs_schema=[
        {
            "key": "pixelId",
            "type": "string",
            "label": "Pixel ID",
            "description": "You must obtain a Pixel ID to use the Reddit Pixel. If you've already set up a Pixel for your website, we recommend that you use the same Pixel ID for your browser and server events.",
            "default": "",
            "secret": False,
            "required": True,
        },
        {
            "key": "userProperties",
            "type": "dictionary",
            "description": "Map of Reddit user parameters and their values. Check out this page for more details: https://business.reddithelp.com/s/article/manual-conversion-events-with-the-reddit-pixel",
            "label": "User parameters",
            "default": {
                "email": "{person.properties.email}",
            },
            "secret": False,
            "required": False,
        },
    ],
    # See our event specification here:
    # https://posthog.com/docs/data/event-spec/ecommerce-events
    # And reddit's here:
    # https://business.reddithelp.com/s/article/manual-conversion-events-with-the-reddit-pixel
    mapping_templates=[
        HogFunctionMappingTemplate(
            name="Page Visit",
            include_by_default=True,
            filters={"events": [{"id": "$pageview", "name": "Pageview", "type": "events"}]},
            inputs_schema=[
                {
                    "key": "eventType",
                    "type": "string",
                    "label": "Event Type",
                    "description": "Check out this page for possible event types: https://business.reddithelp.com/s/article/manual-conversion-events-with-the-reddit-pixel",
                    "default": "PageVisit",
                    "required": True,
                },
                *common_inputs,
            ],
        ),
        HogFunctionMappingTemplate(
            name="Search",
            include_by_default=True,
            filters={"events": [{"id": "Products Searched", "name": "Products Searched", "type": "events"}]},
            inputs_schema=[
                {
                    "key": "eventType",
                    "type": "string",
                    "label": "Event Type",
                    "description": "Check out this page for possible event types: https://business.reddithelp.com/s/article/manual-conversion-events-with-the-reddit-pixel",
                    "default": "Search",
                    "required": True,
                },
                *common_inputs,
            ],
        ),
        HogFunctionMappingTemplate(
            name="Product Added",
            include_by_default=True,
            filters={"events": [{"id": "Product Added", "name": "Product Added", "type": "events"}]},
            inputs_schema=[
                {
                    "key": "eventType",
                    "type": "string",
                    "label": "Event Type",
                    "description": "Check out this page for possible event types: https://business.reddithelp.com/s/article/manual-conversion-events-with-the-reddit-pixel",
                    "default": "AddToCart",
                    "required": True,
                },
                *common_inputs,
            ],
        ),
        HogFunctionMappingTemplate(
            name="Product Added to Wishlist",
            include_by_default=True,
            filters={
                "events": [{"id": "Product Added to Wishlist", "name": "Product Added to Wishlist", "type": "events"}]
            },
            inputs_schema=[
                {
                    "key": "eventType",
                    "type": "string",
                    "label": "Event Type",
                    "description": "Check out this page for possible event types: https://business.reddithelp.com/s/article/manual-conversion-events-with-the-reddit-pixel",
                    "default": "AddToWishlist",
                    "required": True,
                },
                *common_inputs,
            ],
        ),
        HogFunctionMappingTemplate(
            name="Order Completed",
            include_by_default=True,
            filters={"events": [{"id": "Order Completed", "name": "Order Completed", "type": "events"}]},
            inputs_schema=[
                {
                    "key": "eventType",
                    "type": "string",
                    "label": "Event Type",
                    "description": "Check out this page for possible event types: https://business.reddithelp.com/s/article/manual-conversion-events-with-the-reddit-pixel",
                    "default": "Purchase",
                    "required": True,
                },
                *common_inputs,
            ],
        ),
        HogFunctionMappingTemplate(
            name="Product Viewed",
            include_by_default=True,
            filters={"events": [{"id": "Product Viewed", "name": "Product Viewed", "type": "events"}]},
            inputs_schema=[
                {
                    "key": "eventType",
                    "type": "string",
                    "label": "Event Type",
                    "description": "Check out this page for possible event types: https://business.reddithelp.com/s/article/manual-conversion-events-with-the-reddit-pixel",
                    "default": "ViewContent",
                    "required": True,
                },
                *common_inputs,
            ],
        ),
        HogFunctionMappingTemplate(
            name="Lead Generated",
            include_by_default=True,
            filters={"events": [{"id": "Lead Generated", "name": "Lead Generated", "type": "events"}]},
            inputs_schema=[
                {
                    "key": "eventType",
                    "type": "string",
                    "label": "Event Type",
                    "description": "Check out this page for possible event types: https://business.reddithelp.com/s/article/manual-conversion-events-with-the-reddit-pixel",
                    "default": "Lead",
                    "required": True,
                },
                *common_inputs,
            ],
        ),
        HogFunctionMappingTemplate(
            name="Signed Up",
            include_by_default=True,
            filters={"events": [{"id": "Signed Up", "name": "Signed Up", "type": "events"}]},
            inputs_schema=[
                {
                    "key": "eventType",
                    "type": "string",
                    "label": "Event Type",
                    "description": "Check out this page for possible event types: https://business.reddithelp.com/s/article/manual-conversion-events-with-the-reddit-pixel",
                    "default": "SignUp",
                    "required": True,
                },
                *common_inputs,
            ],
        ),
    ],
)
