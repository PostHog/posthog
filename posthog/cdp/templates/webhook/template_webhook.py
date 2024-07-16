from posthog.cdp.templates.hog_function_template import HogFunctionTemplate


template: HogFunctionTemplate = HogFunctionTemplate(
    status="beta",
    id="template-webhook",
    name="HTTP Webhook",
    description="Sends a webhook templated by the incoming event data",
    icon_url="/api/projects/@current/hog_functions/icon/?id=posthog.com&temp=true",
    hog="""
fetch(inputs.url, {
  'headers': inputs.headers,
  'body': inputs.body,
  'method': inputs.method
});
""".strip(),
    inputs_schema=[
        {
            "key": "url",
            "type": "string",
            "label": "Webhook URL",
            "secret": False,
            "required": True,
        },
        {
            "key": "method",
            "type": "choice",
            "label": "Method",
            "secret": False,
            "choices": [
                {
                    "label": "POST",
                    "value": "POST",
                },
                {
                    "label": "PUT",
                    "value": "PUT",
                },
                {
                    "label": "PATCH",
                    "value": "PATCH",
                },
                {
                    "label": "GET",
                    "value": "GET",
                },
                {
                    "label": "DELETE",
                    "value": "DELETE",
                },
            ],
            "default": "POST",
            "required": False,
        },
        {
            "key": "body",
            "type": "json",
            "label": "JSON Body",
            "default": {"event": "{event}", "person": "{person}"},
            "secret": False,
            "required": False,
        },
        {
            "key": "headers",
            "type": "dictionary",
            "label": "Headers",
            "secret": False,
            "required": False,
        },
    ],
)
