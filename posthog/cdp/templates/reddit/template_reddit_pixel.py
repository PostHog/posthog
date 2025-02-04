from posthog.cdp.templates.hog_function_template import HogFunctionMappingTemplate, HogFunctionTemplate

common_inputs = [
    {
        "key": "eventProperties",
        "type": "dictionary",
        "description": "Map of Reddit event attributes and their values. Check out these pages for more details: https://business.reddithelp.com/s/article/manual-conversion-events-with-the-reddit-pixel and https://business.reddithelp.com/s/article/about-event-metadata",
        "label": "Event parameters",
        "default": {
            "conversion_id": "{event.uuid}",
            "products": "{event.properties.products ? arrayMap(product -> ({'id': product.product_id, 'category': product.category, 'name': product.name}), event.properties.product) : [{id: event.properties.product_id, category: event.properties.category, name: event.properties.name}]}",
            "value": "{toFloat(event.properties.value ?? event.properties.revenue)}",
            "currency": "{event.properties.currency}",
        },
        "secret": False,
        "required": False,
    },
]

template_reddit_pixel: HogFunctionTemplate = HogFunctionTemplate(
    free=True,
    status="alpha",
    type="site_destination",
    id="template-reddit-pixel",
    name="Reddit Pixel",
    description="Track how many Reddit users interact with your website.",
    icon_url="/static/services/reddit.png",
    category=["Advertisement"],
    hog="""
// Adds window.rdt and lazily loads the Reddit Pixel script
function initSnippet() {
    !function(w,d){if(!w.rdt){var p=w.rdt=function(){p.sendEvent?p.sendEvent.apply(p,arguments):p.callQueue.push(arguments)};p.callQueue=[];var t=d.createElement("script");t.src="https://www.redditstatic.com/ads/pixel.js",t.async=!0;var s=d.getElementsByTagName("script")[0];s.parentNode.insertBefore(t,s)}}(window,document);
}

export function onLoad({ inputs }) {
    initSnippet();
    let userProperties = {};
    for (const [key, value] of Object.entries(inputs.userProperties)) {
        if (value) {
            userProperties[key] = value;
        }
    };
    rdt('init', inputs.pixelId, userProperties);
}
export function onEvent({ inputs }) {
    let eventProperties = {};
    for (const [key, value] of Object.entries(inputs.eventProperties)) {
        if (value) {
            eventProperties[key] = value;
        }
    };
    rdt('track', inputs.eventType, eventProperties);
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
            name="Add To Cart",
            include_by_default=True,
            filters={"events": [{"id": "Product Added", "name": "Add To Cart", "type": "events"}]},
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
            name="Add To Wishlist",
            include_by_default=True,
            filters={"events": [{"id": "Product Added to Wishlist", "name": "Add To Wishlist", "type": "events"}]},
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
            name="Purchase",
            include_by_default=True,
            filters={"events": [{"id": "Purchase", "name": "Purchase", "type": "events"}]},
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
        # Some events not in our spec:
        HogFunctionMappingTemplate(
            name="View Content",
            include_by_default=True,
            filters={"events": [{"id": "View Content", "name": "ViewContent", "type": "events"}]},
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
            name="Lead",
            include_by_default=True,
            filters={"events": [{"id": "Lead", "name": "Lead", "type": "events"}]},
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
            name="Sign Up",
            include_by_default=True,
            filters={"events": [{"id": "Sign Up", "name": "Sign Up", "type": "events"}]},
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
        HogFunctionMappingTemplate(
            name="name",
            include_by_default=True,
            filters={"events": [{"id": "e.id", "name": "e.name", "type": "events"}]},
            inputs_schema=[
                {
                    "key": "eventType",
                    "type": "string",
                    "label": "Event Type",
                    "description": "Check out this page for possible event types: https://business.reddithelp.com/s/article/manual-conversion-events-with-the-reddit-pixel",
                    "default": "default",
                    "required": True,
                },
                *common_inputs,
            ],
        ),
    ],
)
