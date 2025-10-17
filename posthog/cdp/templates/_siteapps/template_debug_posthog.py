from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="beta",
    free=True,
    type="site_app",
    id="template-debug-posthog-js",
    name="PostHog JS debugger",
    description="Enable extra debugging tools on your posthog-js",
    icon_url="/static/hedgehog/builder-hog-01.png",
    category=["Custom"],
    code_language="javascript",
    code="""
export function onLoad({ inputs, posthog }) {
    if (inputs.enable_debugging) {
        console.log("[PostHog JS debugger site app] Enabling PostHog.js debugging", posthog)
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
