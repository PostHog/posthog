from posthog.cdp.templates.hog_function_template import HogFunctionTemplate


def create_legacy_plugin_template(template_id: str) -> HogFunctionTemplate:
    return HogFunctionTemplate(
        status="free",  # NOTE: This is "free" in the sense that we use it to bypass needing the addon
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
