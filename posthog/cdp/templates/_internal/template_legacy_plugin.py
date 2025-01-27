from posthog.cdp.templates.hog_function_template import HogFunctionTemplate

legacy_plugin_template: HogFunctionTemplate = HogFunctionTemplate(
    status="alpha",
    type="destination",
    id="template-legacy-plugin",
    name="Legacy plugin",
    description="Legacy plugins",
    icon_url="/static/hedgehog/builder-hog-01.png",
    category=["Custom", "Analytics"],
    hog="""
print('not used')
""".strip(),
    inputs_schema=[],
)


def create_legacy_plugin_template(template_id: str) -> HogFunctionTemplate:
    return HogFunctionTemplate(
        status="alpha",
        type="destination",
        id=f"{template_id}",
        name=f"Legacy plugin {template_id}",
        description="Legacy plugins",
        icon_url="/static/hedgehog/builder-hog-01.png",
        category=["Custom"],
        hog="""
    print('not used')
    """.strip(),
        inputs_schema=[],
    )
