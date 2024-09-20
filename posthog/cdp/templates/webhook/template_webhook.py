from posthog.cdp.templates.hog_function_template import SUB_TEMPLATE_COMMON, HogFunctionSubTemplate, HogFunctionTemplate


template: HogFunctionTemplate = HogFunctionTemplate(
    status="beta",
    id="template-webhook",
    name="HTTP Webhook",
    description="Sends a webhook templated by the incoming event data",
    icon_url="/static/posthog-icon.svg",
    hog="""
let res := fetch(inputs.url, {
  'headers': inputs.headers,
  'body': inputs.body,
  'method': inputs.method
});

if (inputs.debug) {
  print('Response', res.status, res.body);
}

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
        {
            "key": "debug",
            "type": "boolean",
            "label": "Log responses",
            "description": "Logs the response of http calls for debugging.",
            "secret": False,
            "required": False,
            "default": False,
        },
    ],
    sub_templates=[
        HogFunctionSubTemplate(
            id="early_access_feature_enrollment",
            name="HTTP Webhook on feature enrollment",
            filters=SUB_TEMPLATE_COMMON["early_access_feature_enrollment"].filters,
        ),
        HogFunctionSubTemplate(
            id="survey_response",
            name="HTTP Webhook on survey response",
            filters=SUB_TEMPLATE_COMMON["survey_response"].filters,
        ),
    ],
)
