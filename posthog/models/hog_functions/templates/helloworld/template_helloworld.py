from posthog.models.hog_functions.hog_function_template import HogFunctionTemplate


template: HogFunctionTemplate = HogFunctionTemplate(
    status="alpha",
    id="template-hello-workd",
    name="Hello world",
    description="Prints your message or hello world!",
    hog="""
print(inputs.message || 'hello world!');
""",
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
