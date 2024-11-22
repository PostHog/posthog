from posthog.cdp.templates.hog_function_template import HogFunctionTemplate

blank_site_app: HogFunctionTemplate = HogFunctionTemplate(
    status="free",
    type="site_app",
    id="template-blank-site-app",
    name="Blank Site App",
    description="Run custom code on your website",
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

blank_site_destination: HogFunctionTemplate = HogFunctionTemplate(
    status="free",
    type="site_destination",
    id="template-blank-site-destination",
    name="Blank Site Destination",
    description="Run code on your site when an event is sent to PostHog",
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
    console.log(`🦔 Sending event: ${globals.event.event}`, globals)
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
