from posthog.cdp.templates.hog_function_template import HogFunctionTemplate

template: HogFunctionTemplate = HogFunctionTemplate(
    status="free",
    type="web",
    id="template-pineapple-analytics",
    name="Pineapple Analytics",
    description="Client side destination for Pineapple Analytics (Test service!)",
    icon_url="/static/services/pineapple.png",
    category=["Custom", "Analytics"],
    hog="""
export async function onLoad({ inputs, posthog }) {
    const url = inputs.host
    console.log('🍍 Loading Pineapple Analytics (takes 5 sec)', { url, inputs })

    await new Promise((resolve) => window.setTimeout(resolve, 5000))
    console.log("🍍 Script loaded")
}

export function onEvent({ posthog, ...globals }) {
    console.log('🍍 Sending event', globals.event.event, globals)
    // window.pineappleAnalytics.capture(payload)
}
""".strip(),
    inputs_schema=[
        {
            "key": "host",
            "type": "string",
            "label": "Pineapple API host",
            "description": "Normally https://get.pineapple.now",
            "default": "https://get.pineapple.now",
            "secret": False,
            "required": True,
        },
        {
            "key": "apiKey",
            "type": "string",
            "label": "API key",
            "secret": False,
            "required": True,
        },
        {
            "key": "userId",
            "type": "string",
            "label": "User ID",
            "description": "The User ID in Pineapple Analytics",
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
