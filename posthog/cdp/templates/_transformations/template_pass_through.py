from posthog.cdp.templates.hog_function_template import HogFunctionTemplate

template: HogFunctionTemplate = HogFunctionTemplate(
    status="alpha",
    type="transformation",
    id="template-blank-transformation",
    name="Custom transformation",
    description="This is a starter template for custom transformations",
    icon_url="/static/hedgehog/builder-hog-01.png",
    category=["Custom"],
    hog="""
// This is a blank template for custom transformations
// The function receives `event` as a global object and expects it to be returned
// If you return null then the event will be discarded
return event
""".strip(),
    inputs_schema=[],
)
