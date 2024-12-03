from posthog.cdp.templates.hog_function_template import HogFunctionTemplate

blank_site_destination: HogFunctionTemplate = HogFunctionTemplate(
    status="client-side",
    type="site_destination",
    id="template-blank-site-destination",
    name="New client-side destination",
    description="Run code on your website when an event is sent to PostHog. Works only with posthog-js when opt_in_site_apps is set to true.",
    icon_url="/static/hedgehog/builder-hog-01.png",
    category=["Custom", "Analytics"],
    hog="""
export async function onLoad({ inputs, posthog }) {
    console.log('🦔 Loading (takes 1 sec)', { inputs })
    // onEvent will not be called until this function resolves
    await new Promise((resolve) => window.setTimeout(resolve, 1000))
    console.log("🦔 Script loaded")
}
export function onEvent({ posthog, ...globals }) {
    const { event, person } = globals
    console.log(`🦔 Sending event: ${event.event}`, globals)
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
)
