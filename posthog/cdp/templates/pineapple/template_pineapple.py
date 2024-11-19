from posthog.cdp.templates.hog_function_template import HogFunctionTemplate

template: HogFunctionTemplate = HogFunctionTemplate(
    status="free",
    type="web",
    id="template-pineapple",
    name="Pineapple Analytics",
    description="Client side destination for Pineapple Analytics",
    icon_url="/static/services/pineapple.png",
    category=["Custom", "Analytics"],
    hog="""
export async function onLoad({ inputs, posthog }) {
    const url = inputs.host
    console.log('🍍 Loading Pineapple Analytics', { url, inputs })
    // await loadScript(url + '/js?t=' + new Date().getTime())
}

// behind the scenes: posthog.on('eventCaptured', (event) => {})
export function onEvent({ event, person, inputs, posthog }) {
    const { userId, additionalProperties } = inputs
    const payload = { event, person, userId, additionalProperties }

    console.log('🍍 Sending event', { payload })
    // window.pineappleAnalytics.capture(payload)
}
""".strip(),
    inputs_schema=[
        {
            "key": "host",
            "type": "string",
            "label": "Pineapple API host",
            "description": "Normally https://nom.pineapple.now",
            "default": "https://nom.pineapple.now",
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
