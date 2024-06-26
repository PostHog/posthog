from posthog.cdp.templates.hog_function_template import HogFunctionTemplate


template: HogFunctionTemplate = HogFunctionTemplate(
    status="alpha",
    id="template-hello-workd",
    name="Hello world",
    description="Prints your message or hello world!",
    icon_url="/api/projects/@current/hog_functions/icon/?id=posthog.com&temp=true",
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
