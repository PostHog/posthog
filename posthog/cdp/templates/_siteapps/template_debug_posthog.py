from posthog.cdp.templates.hog_function_template import HogFunctionTemplate

template: HogFunctionTemplate = HogFunctionTemplate(
    status="client-side",
    type="site_app",
    id="template-debug-posthog-js",
    name="PostHog JS debugger",
    description="Enable extra debugging tools on your posthog-js",
    icon_url="/static/hedgehog/builder-hog-01.png",
    category=["Custom"],
    hog="""
export function onLoad({ inputs, posthog }) {
    console.log("Enabling PostHog.js debugging", posthog)

    if (inputs.enable_debugging) {
        posthog.debug(true)
    }

    if (inputs.capture_config) {
        posthog.capture("posthog-js debug", {
            config: posthog.config
        })
    }
}
""".strip(),
    inputs_schema=[
        {
            "key": "capture_config",
            "type": "boolean",
            "label": "Capture debug event on load",
            "secret": False,
            "default": False,
            "required": False,
            "description": "Whether to capture an event on load including the posthog config",
        },
        {
            "key": "enable_debugging",
            "type": "boolean",
            "label": "Enable debugging",
            "secret": False,
            "default": False,
            "required": False,
        },
    ],
)
