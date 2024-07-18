from posthog.cdp.templates.hog_function_template import HogFunctionTemplate


template: HogFunctionTemplate = HogFunctionTemplate(
    status="alpha",
    id="template-hello-world",
    name="Hello world",
    description="Prints your message or hello world!",
    icon_url="/static/posthog-icon.svg?temp=true",
    hog="""
print(inputs.message ?? 'hello world!');
""".strip(),
    inputs_schema=[
        {
            "key": "message",
            "type": "string",
            "label": "Message to print",
            "secret": False,
            "required": False,
        }
    ],
)
