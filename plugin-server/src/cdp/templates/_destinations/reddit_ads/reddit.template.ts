import { HogFunctionInputSchemaType } from '~/cdp/types'
import { HogFunctionTemplate } from '~/cdp/types'

const build_inputs = (): HogFunctionInputSchemaType[] => {
    return [
        {
            key: 'rdt_cid',
            type: 'string',
            label: 'Reddit Click ID (rdt_cid)',
            description: 'The Reddit click ID (rdt_cid) associated with this conversion.',
            default: '{person.properties.rdt_cid ?? person.properties.$initial_rdt_cid}',
            secret: false,
            required: false,
        },
        {
            key: 'eventProperties',
            type: 'dictionary',
            description:
                'Map of Reddit event attributes and their values. Check out these pages for more details: https://business.reddithelp.com/s/article/manual-conversion-events-with-the-reddit-pixel and https://business.reddithelp.com/s/article/about-event-metadata',
            label: 'Event parameters',
            default: {
                conversion_id: '{event.uuid}',
                products:
                    "{event.properties.products ? arrayMap(product -> ({'id': product.product_id, 'category': product.category, 'name': product.name}), event.properties.products) : event.properties.product_id ? [{'id': event.properties.product_id, 'category': event.properties.category, 'name': event.properties.name}] : null}",
                value: '{toFloat(event.properties.value ?? event.properties.revenue ?? event.properties.price)}',
                currency: '{event.properties.currency}',
            },
            secret: false,
            required: false,
        },
    ]
}

export const template: HogFunctionTemplate = {
    free: false,
    status: 'alpha',
    type: 'destination',
    id: 'template-reddit-conversions-api',
    name: 'Reddit Conversions API',
    description: 'Track how many Reddit users interact with your website.',
    icon_url: '/static/services/reddit.png',
    category: ['Advertisement'],
    code_language: 'hog',
    code: `
if (empty(inputs.accountId) or empty(inputs.conversionsAccessToken)) {
    throw Error('Account ID and access token are required')
}

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

if (not empty(inputs.rdt_cid)) {
    eventData['click_id'] := inputs.rdt_cid;
}

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
`,
    inputs_schema: [
        {
            key: 'accountId',
            type: 'string',
            label: 'Reddit Ads account ID',
            description:
                'The ID of the Reddit Ads account that the conversion event belongs to. Your account ID may or may not contain the t2_ prefix.', // this is copied verbatim from https://ads-api.reddit.com/docs/v2/#section/Best-practices
            default: '',
            secret: false,
            required: true,
        },
        {
            key: 'conversionsAccessToken',
            type: 'string',
            label: 'Conversion Access Token',
            description: 'You must obtain a Conversion Access Token.',
            default: '',
            secret: true,
            required: true,
        },
        {
            key: 'userProperties',
            type: 'dictionary',
            description:
                'Map of Reddit user parameters and their values. Check out this page for more details: https://business.reddithelp.com/s/article/manual-conversion-events-with-the-reddit-pixel',
            label: 'User parameters',
            default: {
                email: '{person.properties.email}',
                screen_dimensions:
                    "{{'width': person.properties.$screen_width, 'height': person.properties.$screen_height}}",
                user_agent: '{person.properties.$raw_user_agent}',
                ip: '{sha256Hex(event.properties.$ip)}', // use event properties here, as $ip is not a person property
            },
            secret: false,
            required: false,
        },
    ],
    mapping_templates: [
        {
            name: 'Page Visit',
            include_by_default: true,
            filters: {
                events: [{ id: '$pageview', name: 'Pageview', type: 'events' }],
            },
            inputs_schema: [
                {
                    key: 'eventType',
                    type: 'string',
                    label: 'Event Type',
                    description:
                        'Check out this page for possible event types: https://business.reddithelp.com/s/article/manual-conversion-events-with-the-reddit-pixel',
                    default: 'PageVisit',
                    required: true,
                },
                ...build_inputs(),
            ],
        },
        {
            name: 'Search',
            include_by_default: true,
            filters: {
                events: [{ id: 'Products Searched', type: 'events' }],
            },
            inputs_schema: [
                {
                    key: 'eventType',
                    type: 'string',
                    label: 'Event Type',
                    description:
                        'Check out this page for possible event types: https://business.reddithelp.com/s/article/manual-conversion-events-with-the-reddit-pixel',
                    default: 'Search',
                    required: true,
                },
                ...build_inputs(),
            ],
        },
        {
            name: 'Product Added',
            include_by_default: true,
            filters: {
                events: [{ id: 'Product Added', type: 'events' }],
            },
            inputs_schema: [
                {
                    key: 'eventType',
                    type: 'string',
                    label: 'Event Type',
                    description:
                        'Check out this page for possible event types: https://business.reddithelp.com/s/article/manual-conversion-events-with-the-reddit-pixel',
                    default: 'AddToCart',
                    required: true,
                },
                ...build_inputs(),
            ],
        },
        {
            name: 'Product Added to Wishlist',
            include_by_default: true,
            filters: {
                events: [{ id: 'Product Added to Wishlist', type: 'events' }],
            },
            inputs_schema: [
                {
                    key: 'eventType',
                    type: 'string',
                    label: 'Event Type',
                    description:
                        'Check out this page for possible event types: https://business.reddithelp.com/s/article/manual-conversion-events-with-the-reddit-pixel',
                    default: 'AddToWishlist',
                    required: true,
                },
                ...build_inputs(),
            ],
        },
        {
            name: 'Order Completed',
            include_by_default: true,
            filters: {
                events: [{ id: 'Order Completed', type: 'events' }],
            },
            inputs_schema: [
                {
                    key: 'eventType',
                    type: 'string',
                    label: 'Event Type',
                    description:
                        'Check out this page for possible event types: https://business.reddithelp.com/s/article/manual-conversion-events-with-the-reddit-pixel',
                    default: 'Purchase',
                    required: true,
                },
                ...build_inputs(),
            ],
        },
        {
            name: 'Product Viewed',
            include_by_default: true,
            filters: {
                events: [{ id: 'Product Viewed', type: 'events' }],
            },
            inputs_schema: [
                {
                    key: 'eventType',
                    type: 'string',
                    label: 'Event Type',
                    description:
                        'Check out this page for possible event types: https://business.reddithelp.com/s/article/manual-conversion-events-with-the-reddit-pixel',
                    default: 'ViewContent',
                    required: true,
                },
                ...build_inputs(),
            ],
        },
        {
            name: 'Lead Generated',
            include_by_default: true,
            filters: {
                events: [{ id: 'Lead Generated', type: 'events' }],
                bytecode: ['_H', 1, 32, 'Lead Generated', 32, 'event', 1, 1, 11, 3, 1, 4, 1],
            },
            inputs_schema: [
                {
                    key: 'eventType',
                    type: 'string',
                    label: 'Event Type',
                    description:
                        'Check out this page for possible event types: https://business.reddithelp.com/s/article/manual-conversion-events-with-the-reddit-pixel',
                    default: 'Lead',
                    required: true,
                },
                ...build_inputs(),
            ],
        },
        {
            name: 'Signed Up',
            include_by_default: true,
            filters: {
                events: [{ id: 'Signed Up', type: 'events' }],
                bytecode: ['_H', 1, 32, 'Signed Up', 32, 'event', 1, 1, 11, 3, 1, 4, 1],
            },
            inputs_schema: [
                {
                    key: 'eventType',
                    type: 'string',
                    label: 'Event Type',
                    description:
                        'Check out this page for possible event types: https://business.reddithelp.com/s/article/manual-conversion-events-with-the-reddit-pixel',
                    default: 'SignUp',
                    required: true,
                },
                ...build_inputs(),
            ],
        },
    ],
}
