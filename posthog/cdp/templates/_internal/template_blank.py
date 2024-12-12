from posthog.cdp.templates.hog_function_template import HogFunctionMapping, HogFunctionTemplate

blank_site_destination: HogFunctionTemplate = HogFunctionTemplate(
    status="client-side",
    type="site_destination",
    id="template-blank-site-destination",
    name="New client-side destination",
    description="New destination with complex event mapping. Works only with posthog-js when opt_in_site_apps is set to true.",
    icon_url="/static/hedgehog/builder-hog-01.png",
    category=["Custom", "Analytics"],
    hog="""
export async function onLoad({ inputs, posthog }) {
    console.log('🦔 Loading (takes 1 sec)', { inputs })
    // onEvent will not be called until this function resolves
    await new Promise((resolve) => window.setTimeout(resolve, 1000))
    console.log("🦔 Script loaded")
}
export function onEvent({ inputs, posthog }) {
    console.log(`🦔 Sending event of type ${inputs.eventType}`, inputs.payload)
    // fetch('url', { method: 'POST', body: JSON.stringify(inputs.payload) })
}
""".strip(),
    inputs_schema=[
        {
            "key": "name",
            "type": "string",
            "label": "Name",
            "description": "What's your name?",
            "default": "Max",
        },
        {
            "key": "userId",
            "type": "string",
            "label": "User ID",
            "description": "User ID",
            "default": "{event.distinct_id}",
            "secret": False,
            "required": True,
        },
        {
            "key": "additionalProperties",
            "type": "json",
            "label": "Additional properties",
            "description": "Additional properties for the Exported Object.",
            "default": {
                "email": "{person.properties.email}",
                "browser": "{event.properties.$browser}",
            },
            "secret": False,
            "required": True,
        },
    ],
    mappings=[
        HogFunctionMapping(
            filters={"events": [{"id": "$pageview", "type": "events"}]},
            inputs_schema=[
                {
                    "key": "eventType",
                    "type": "string",
                    "label": "Event Type",
                    "description": "The destination's event type",
                    "default": "acquisition",
                    "required": True,
                },
                {
                    "key": "payload",
                    "type": "json",
                    "label": "Payload",
                    "description": "Payload sent to the destination.",
                    "default": {
                        "event": "{event}",
                        "person": "{person}",
                    },
                    "secret": False,
                    "required": True,
                },
            ],
        ),
        HogFunctionMapping(
            filters={"events": [{"id": "$autocapture", "type": "events"}]},
            inputs_schema=[
                {
                    "key": "eventType",
                    "type": "string",
                    "label": "Event Type",
                    "description": "The destination's event type",
                    "default": "conversion",
                    "required": True,
                },
                {
                    "key": "payload",
                    "type": "json",
                    "label": "Payload",
                    "description": "Payload sent to the destination.",
                    "default": {
                        "event": "{event}",
                        "person": "{person}",
                    },
                    "secret": False,
                    "required": True,
                },
            ],
        ),
        HogFunctionMapping(
            filters={"events": [{"id": "$pageleave", "type": "events"}]},
            inputs_schema=[
                {
                    "key": "eventType",
                    "type": "string",
                    "label": "Event Type",
                    "description": "The destination's event type",
                    "default": "retention",
                    "required": True,
                },
                {
                    "key": "payload",
                    "type": "json",
                    "label": "Payload",
                    "description": "Payload sent to the destination.",
                    "default": {
                        "event": "{event}",
                        "person": "{person}",
                    },
                    "secret": False,
                    "required": True,
                },
            ],
        ),
    ],
)

blank_site_app: HogFunctionTemplate = HogFunctionTemplate(
    status="client-side",
    type="site_app",
    id="template-blank-site-app",
    name="New site app",
    description="Run custom JavaScript on your website. Works only with posthog-js when opt_in_site_apps is set to true.",
    icon_url="/static/hedgehog/builder-hog-03.png",
    category=["Custom", "Analytics"],
    hog="""
export function onLoad({ inputs, posthog }) {
    console.log(`Hello ${inputs.name} from your new Site App!`)
}
""".strip(),
    inputs_schema=[
        {
            "key": "name",
            "type": "string",
            "label": "Name",
            "description": "What's your name?",
            "default": "Max",
        },
    ],
)
