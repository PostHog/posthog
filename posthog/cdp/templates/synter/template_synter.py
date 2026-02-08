from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="stable",
    free=True,
    type="destination",
    id="template-synter",
    name="Synter",
    description="Send events to Synter for cross-platform ad attribution and conversion tracking. Automatically attribute conversions to Google, Meta, LinkedIn, TikTok, and other ad platforms.",
    icon_url="https://syntermedia.ai/icon.png",
    category=["Attribution", "Advertising", "Analytics"],
    code_language="hog",
    code="""
// Build the event payload for Synter
let payload := {
    'event_name': event.event,
    'event_id': event.uuid,
    'event_time': event.timestamp,
    'synter_id': event.distinct_id,
    'properties': event.properties,
    'page_url': event.properties.$current_url ?? event.properties.url,
    'referrer': event.properties.$referrer,
    'user_agent': event.properties.$browser,
    'source': 'posthog'
};

// Add attribution click IDs if present in properties
if (not empty(event.properties.gclid)) {
    payload.gclid := event.properties.gclid;
}
if (not empty(event.properties.fbclid)) {
    payload.fbclid := event.properties.fbclid;
}
if (not empty(event.properties.fbc)) {
    payload.fbc := event.properties.fbc;
}
if (not empty(event.properties.fbp)) {
    payload.fbp := event.properties.fbp;
}
if (not empty(event.properties.ttclid)) {
    payload.ttclid := event.properties.ttclid;
}
if (not empty(event.properties.li_fat_id)) {
    payload.li_fat_id := event.properties.li_fat_id;
}
if (not empty(event.properties.msclkid)) {
    payload.msclkid := event.properties.msclkid;
}
if (not empty(event.properties.rdt_cid)) {
    payload.rdt_cid := event.properties.rdt_cid;
}

// Add value/revenue if present
if (not empty(event.properties.value)) {
    payload.value := event.properties.value;
}
if (not empty(event.properties.revenue)) {
    payload.value := event.properties.revenue;
}
if (not empty(event.properties.currency)) {
    payload.currency := event.properties.currency;
}

// Add person properties if include_person is enabled
if (inputs.include_person and not empty(person)) {
    payload.person := {
        'id': person.id,
        'properties': person.properties
    };
}

// Make the request to Synter
let res := fetch(f'https://syntermedia.ai/api/pixel/posthog-webhook', {
    'method': 'POST',
    'headers': {
        'Content-Type': 'application/json',
        'X-Synter-Site-Key': inputs.site_key
    },
    'body': payload
});

if (res.status >= 400) {
    throw Error(f'Synter API error: {res.status} - {res.body}');
}

if (inputs.debug) {
    print('Synter response:', res.status, res.body);
}
""".strip(),
    inputs_schema=[
        {
            "key": "site_key",
            "type": "string",
            "label": "Synter Site Key",
            "description": "Your Synter site key (e.g., ws_abc123). Find this in Synter → Settings → Conversions.",
            "secret": True,
            "required": True,
            "hidden": False,
        },
        {
            "key": "include_person",
            "type": "boolean",
            "label": "Include person properties",
            "description": "Send PostHog person properties along with events for richer attribution data.",
            "secret": False,
            "required": False,
            "default": True,
            "hidden": False,
        },
        {
            "key": "debug",
            "type": "boolean",
            "label": "Log responses",
            "description": "Log API responses for debugging. Disable in production.",
            "secret": False,
            "required": False,
            "default": False,
            "hidden": False,
        },
    ],
)
