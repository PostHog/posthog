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
            "search_string": "{event.properties.query ?? event.properties.search_string}",
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
    {
        "key": "eventId",
        "type": "string",
        "description": "The ID of the event. This will be used for deduplication. Check out this page for more details: https://business-api.tiktok.com/portal/docs?id=1771100965992450",
        "label": "Event ID",
        "default": "{event.uuid}",
        "secret": False,
        "required": True,
    },
]

template_tiktok_pixel: HogFunctionTemplate = HogFunctionTemplate(
    status="beta",
    free=False,
    type="site_destination",
    id="template-tiktok-pixel",
    name="TikTok Pixel",
    description="Track how many TikTok users interact with your website.",
    icon_url="/static/services/tiktok.png",
    category=["Advertisement"],
    hog="""
// Adds window.snaptr and lazily loads the TikTok Pixel script
function initSnippet() {
    !function (w, d, t) {
    w.TiktokAnalyticsObject=t;var ttq=w[t]=w[t]||[];ttq.methods=["page","track","identify","instances","debug","on","off","once","ready","alias","group","enableCookie","disableCookie","holdConsent","revokeConsent","grantConsent"],ttq.setAndDefer=function(t,e){t[e]=function(){t.push([e].concat(Array.prototype.slice.call(arguments,0)))}};for(var i=0;i<ttq.methods.length;i++)ttq.setAndDefer(ttq,ttq.methods[i]);ttq.instance=function(t){for(
    var e=ttq._i[t]||[],n=0;n<ttq.methods.length;n++)ttq.setAndDefer(e,ttq.methods[n]);return e},ttq.load=function(e,n){var r="https://analytics.tiktok.com/i18n/pixel/events.js",o=n&&n.partner;ttq._i=ttq._i||{},ttq._i[e]=[],ttq._i[e]._u=r,ttq._t=ttq._t||{},ttq._t[e]=+new Date,ttq._o=ttq._o||{},ttq._o[e]=n||{};n=document.createElement("script")
    ;n.type="text/javascript",n.async=!0,n.src=r+"?sdkid="+e+"&lib="+t;e=document.getElementsByTagName("script")[0];e.parentNode.insertBefore(n,e)};
    }(window, document, 'ttq')
}

export function onLoad({ inputs }) {
    initSnippet();
    ttq.load(inputs.pixelId);

    let userProperties = {};
    for (const [key, value] of Object.entries(inputs.userProperties)) {
        if (value) {
            userProperties[key] = value;
        }
    };
    ttq.instance(inputs.pixelId).identify(userProperties)
}
export function onEvent({ inputs }) {
    let eventProperties = {};
    for (const [key, value] of Object.entries(inputs.eventProperties)) {
        if (value) {
            eventProperties[key] = value;
        }
    };
    ttq.instance(settings.pixelCode).track(
        payload.event,
        {
            contents: payload.contents ? payload.contents : [],
            content_type: payload.content_type ? payload.content_type : undefined,
            currency: payload.currency ? payload.currency : 'USD',
            value: payload.value || payload.value === 0 ? payload.value : undefined,
            query: payload.query ? payload.query : undefined,
            description: payload.description ? payload.description : undefined,
            order_id: payload.order_id ? payload.order_id : undefined,
            shop_id: payload.shop_id ? payload.shop_id : undefined
        },
        {
            event_id: inputs.eventId
        }
    )
}
""".strip(),
    inputs_schema=[
        {
            "key": "pixelId",
            "type": "string",
            "label": "Pixel ID",
            "description": "You must obtain a Pixel ID to use the TikTok     Pixel. If you've already set up a Pixel for your website, we recommend that you use the same Pixel ID for your browser and server events.",
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
                "email": "{sha256Hex(person.properties.email)}",
                "phone_number": "{sha256Hex(person.properties.phone)}",
                "external_id": "{sha256Hex(person.id)}",
                "first_name": "{person.properties.first_name}",
                "last_name": "{person.properties.last_name}",
                "city": "{person.properties.$geoip_city_name}",
                "state": "{person.properties.$geoip_subdivision_1_name}",
                "country": "{person.properties.$geoip_country_name}",
                "zip_code": "{person.properties.$geoip_postal_code}",
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
                    "description": "Check out this page for possible event types: https://ads.tiktok.com/help/article/supported-standard-events",
                    "default": "Pageview",
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
                    "description": "Check out this page for possible event types: https://ads.tiktok.com/help/article/supported-standard-events",
                    "default": "CompletePayment",
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
                    "description": "Check out this page for possible event types: https://ads.tiktok.com/help/article/supported-standard-events",
                    "default": "ViewContent",
                    "required": True,
                },
                *common_inputs,
            ],
        ),
        HogFunctionMappingTemplate(
            name="Product Clicked",
            include_by_default=True,
            filters={"events": [{"id": "Product Clicked", "type": "events"}]},
            inputs_schema=[
                {
                    "key": "eventType",
                    "type": "string",
                    "label": "Event Type",
                    "description": "Check out this page for possible event types: https://ads.tiktok.com/help/article/supported-standard-events",
                    "default": "ClickButton",
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
                    "description": "Check out this page for possible event types: https://ads.tiktok.com/help/article/supported-standard-events",
                    "default": "Search",
                    "required": True,
                },
                *common_inputs,
            ],
        ),
        HogFunctionMappingTemplate(
            name="Add to Wishlist",
            include_by_default=True,
            filters={"events": [{"id": "Add to Wishlist", "type": "events"}]},
            inputs_schema=[
                {
                    "key": "eventType",
                    "type": "string",
                    "label": "Event Type",
                    "description": "Check out this page for possible event types: https://ads.tiktok.com/help/article/supported-standard-events",
                    "default": "AddToWishlist",
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
                    "description": "Check out this page for possible event types: https://ads.tiktok.com/help/article/supported-standard-events",
                    "default": "AddToCart",
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
                    "description": "Check out this page for possible event types: https://ads.tiktok.com/help/article/supported-standard-events",
                    "default": "InitiateCheckout",
                    "required": True,
                },
                *common_inputs,
            ],
        ),
        HogFunctionMappingTemplate(
            name="Add Payment Info",
            include_by_default=True,
            filters={"events": [{"id": "Add Payment Info", "type": "events"}]},
            inputs_schema=[
                {
                    "key": "eventType",
                    "type": "string",
                    "label": "Event Type",
                    "description": "Check out this page for possible event types: https://ads.tiktok.com/help/article/supported-standard-events",
                    "default": "AddPaymentInfo",
                    "required": True,
                },
                *common_inputs,
            ],
        ),
        HogFunctionMappingTemplate(
            name="Place an Order",
            include_by_default=True,
            filters={"events": [{"id": "Place an Order", "type": "events"}]},
            inputs_schema=[
                {
                    "key": "eventType",
                    "type": "string",
                    "label": "Event Type",
                    "description": "Check out this page for possible event types: https://ads.tiktok.com/help/article/supported-standard-events",
                    "default": "PlaceAnOrder",
                    "required": True,
                },
                *common_inputs,
            ],
        ),
        HogFunctionMappingTemplate(
            name="Signed Up",
            include_by_default=True,
            filters={"events": [{"id": "Signed Up", "type": "events"}]},
            inputs_schema=[
                {
                    "key": "eventType",
                    "type": "string",
                    "label": "Event Type",
                    "description": "Check out this page for possible event types: https://ads.tiktok.com/help/article/supported-standard-events",
                    "default": "CompleteRegistration",
                    "required": True,
                },
                *common_inputs,
            ],
        ),
    ],
)
