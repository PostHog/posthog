from posthog.cdp.templates.hog_function_template import SiteFunctionTemplate

template: SiteFunctionTemplate = SiteFunctionTemplate(
    status="beta",
    type="destination",
    id="template-pineapple",
    name="Pineapple Analytics",
    description="Client side destination for Pineapple Analytics",
    icon_url="/static/posthog-icon.svg",
    category=["Custom", "Analytics"],
    source="""
export async function onLoad({ inputs, posthog }) {
    const url = inputs.host
    console.log('🍍 Loading Pineapple Analytics', { url, inputs })
    // await loadScript(url + '/js?t=' + new Date().getTime())
}

// behind the scenes: posthog.on('eventCaptured', (event) => {})
export function onEvent({ event, person, inputs, posthog }) {
    const { browser, userId } = inputs
    const payload = { event, person, browser, userId }

    console.log('🍍 Sending event', { payload })
    // window.pineappleAnalytics.capture(payload)
}
""".strip(),
    inputs_schema=[
        {
            "key": "host",
            "type": "string",
            "label": "Pineapple API host",
            "description": "Normally https://t.pineapple.space",
            "default": "https://t.pineapple.space",
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
            "key": "browser",
            "type": "string",
            "label": "Browser",
            "default": "{event.properties.$browser}",
            "secret": False,
            "required": False,
        },
    ],
)
