from posthog.cdp.templates.hog_function_template import HogFunctionMappingTemplate, HogFunctionTemplate


def build_inputs(multiProductEvent=False):
    return [
        {
            "key": "eventProperties",
            "type": "dictionary",
            "description": "Map of TikTok event attributes and their values. Check out this page for more details: https://business-api.tiktok.com/portal/docs?id=1739585702922241#item-link-Parameters",
            "label": "Event parameters",
            "default": {
                "content_ids": "{arrayMap(product -> product.product_id, event.properties.products ?? [])}"
                if multiProductEvent
                else "{event.properties.product_id ? [event.properties.product_id] : null}",
                "contents": "{arrayMap(product -> ({ 'content_id': product.product_id, 'price': product.price, 'content_category': product.category, 'content_name': product.name, 'brand': product.brand, 'quantity': product.quantity }), event.properties.products ?? [])}"
                if multiProductEvent
                else "{[{ 'content_id': event.properties.product_id, 'price': event.properties.price, 'content_category': event.properties.category, 'content_name': event.properties.name, 'brand': event.properties.brand, 'quantity': event.properties.quantity }]}",
                "currency": "{event.properties.currency ?? 'USD'}",
                "value": "{toFloat(event.properties.value ?? event.properties.revenue ?? event.properties.price)}",
                "num_items": "{arrayReduce((acc, curr) -> acc + curr.quantity, event.properties.products ?? [], 0)}"
                if multiProductEvent
                else "{event.properties.quantity}",
                "search_string": "{event.properties.query}",
                "description": "",
            },
            "secret": False,
            "required": False,
        },
        {
            "key": "contentType",
            "type": "choice",
            "description": "Type of the product item. When the content_id in the Contents field is specified as a sku_id, set this field to product. When the content_id in the Contents field is specified as an item_group_id, set this field to product_group.",
            "label": "Content Type",
            "default": "product_group" if multiProductEvent else "product",
            "choices": [
                {"value": "product", "label": "Product"},
                {"value": "product_group", "label": "Product Group"},
            ],
            "secret": False,
            "required": True,
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
    status="alpha",
    free=False,
    type="site_destination",
    id="template-tiktok-pixel",
    name="TikTok Pixel",
    description="Track how many TikTok users interact with your website. Note that this destination will set third-party cookies.",
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
        if (value || value === '') {
            userProperties[key] = value;
        }
    };
    ttq.instance(inputs.pixelId).identify(userProperties);
}
export function onEvent({ inputs }) {
    let eventProperties = {};

    for (const [key, value] of Object.entries(inputs.eventProperties)) {
        if (value !== undefined) {
            eventProperties[key] = value;
        }
    };

    if (inputs.contentType !== undefined) {
        eventProperties.content_type = inputs.contentType;
    }

    ttq.instance(inputs.pixelId).track(
        inputs.eventType,
        eventProperties,
        {
            event_id: inputs.eventId
        }
    );
}
""".strip(),
    inputs_schema=[
        {
            "key": "pixelId",
            "type": "string",
            "label": "Pixel ID",
            "description": "You must obtain a Pixel ID to use the TikTok Pixel. If you've already set up a Pixel for your website, we recommend that you use the same Pixel ID for your browser and server events.",
            "default": "",
            "secret": False,
            "required": True,
        },
        {
            "key": "userProperties",
            "type": "dictionary",
            "description": "Map of TikTok user parameters and their values. Check out this page for more details: https://business-api.tiktok.com/portal/docs?id=1739585700402178#item-link-Identity%20information%20supported",
            "label": "User parameters",
            "default": {
                "email": "{not empty(person.properties.email) ? sha256Hex(lower(person.properties.email)) : ''}",
                "first_name": "{not empty(person.properties.first_name) ? sha256Hex(lower(person.properties.first_name)) : ''}",
                "last_name": "{not empty(person.properties.last_name) ? sha256Hex(lower(person.properties.last_name)) : ''}",
                "phone": "{not empty(person.properties.phone) ? sha256Hex(person.properties.phone) : ''}",
                "external_id": "{not empty(person.id) ? sha256Hex(person.id) : ''}",
                "city": "{not empty(person.properties.$geoip_city_name) ? replaceAll(lower(person.properties.$geoip_city_name), ' ', '') : null}",
                "state": "{lower(person.properties.$geoip_subdivision_1_code)}",
                "country": "{lower(person.properties.$geoip_country_code)}",
                "zip_code": "{not empty (person.properties.$geoip_postal_code) ? sha256Hex(replaceAll(lower(person.properties.$geoip_postal_code), ' ', '')) : null}",
                "ttclid": "{person.properties.ttclid ?? person.properties.$initial_ttclid}",
                "ip": "{event.properties.$ip}",
                "user_agent": "{event.properties.$raw_user_agent}",
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
                    "description": "Check out this page for possible event types: https://business-api.tiktok.com/portal/docs?id=1739585702922241#item-link-Event%20codes",
                    "default": "Pageview",
                    "required": True,
                },
                *build_inputs(multiProductEvent=False),
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
                    "description": "Check out this page for possible event types: https://business-api.tiktok.com/portal/docs?id=1739585702922241#item-link-Event%20codes",
                    "default": "CompletePayment",
                    "required": True,
                },
                *build_inputs(multiProductEvent=True),
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
                    "description": "Check out this page for possible event types: https://business-api.tiktok.com/portal/docs?id=1739585702922241#item-link-Event%20codes",
                    "default": "ViewContent",
                    "required": True,
                },
                *build_inputs(multiProductEvent=False),
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
                    "description": "Check out this page for possible event types: https://business-api.tiktok.com/portal/docs?id=1739585702922241#item-link-Event%20codes",
                    "default": "ClickButton",
                    "required": True,
                },
                *build_inputs(multiProductEvent=False),
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
                    "description": "Check out this page for possible event types: https://business-api.tiktok.com/portal/docs?id=1739585702922241#item-link-Event%20codes",
                    "default": "Search",
                    "required": True,
                },
                *build_inputs(multiProductEvent=False),
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
                    "description": "Check out this page for possible event types: https://business-api.tiktok.com/portal/docs?id=1739585702922241#item-link-Event%20codes",
                    "default": "AddToWishlist",
                    "required": True,
                },
                *build_inputs(multiProductEvent=False),
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
                    "description": "Check out this page for possible event types: https://business-api.tiktok.com/portal/docs?id=1739585702922241#item-link-Event%20codes",
                    "default": "AddToCart",
                    "required": True,
                },
                *build_inputs(multiProductEvent=False),
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
                    "description": "Check out this page for possible event types: https://business-api.tiktok.com/portal/docs?id=1739585702922241#item-link-Event%20codes",
                    "default": "InitiateCheckout",
                    "required": True,
                },
                *build_inputs(multiProductEvent=True),
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
                    "description": "Check out this page for possible event types: https://business-api.tiktok.com/portal/docs?id=1739585702922241#item-link-Event%20codes",
                    "default": "AddPaymentInfo",
                    "required": True,
                },
                *build_inputs(multiProductEvent=True),
            ],
        ),
        HogFunctionMappingTemplate(
            name="Order Placed",
            include_by_default=True,
            filters={"events": [{"id": "Order Placed", "type": "events"}]},
            inputs_schema=[
                {
                    "key": "eventType",
                    "type": "string",
                    "label": "Event Type",
                    "description": "Check out this page for possible event types: https://business-api.tiktok.com/portal/docs?id=1739585702922241#item-link-Event%20codes",
                    "default": "PlaceAnOrder",
                    "required": True,
                },
                *build_inputs(multiProductEvent=True),
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
                    "description": "Check out this page for possible event types: https://business-api.tiktok.com/portal/docs?id=1739585702922241#item-link-Event%20codes",
                    "default": "CompleteRegistration",
                    "required": True,
                },
                *build_inputs(multiProductEvent=True),
            ],
        ),
    ],
)
