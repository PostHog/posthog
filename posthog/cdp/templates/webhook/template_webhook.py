from posthog.cdp.templates.hog_function_template import SUB_TEMPLATE_COMMON, HogFunctionSubTemplate, HogFunctionTemplate


template: HogFunctionTemplate = HogFunctionTemplate(
    status="beta",
    free=False,
    type="destination",
    id="template-webhook",
    name="HTTP Webhook",
    description="Sends a webhook templated by the incoming event data",
    icon_url="/static/posthog-icon.svg",
    category=["Custom"],
    hog="""
let payload := {
  'headers': inputs.headers,
  'body': inputs.body,
  'method': inputs.method
}

if (inputs.debug) {
  print('Request', inputs.url, payload)
}

let res := fetch(inputs.url, payload);

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
            "hidden": False,
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
            "hidden": False,
        },
        {
            "key": "body",
            "type": "json",
            "label": "JSON Body",
            "default": {"event": "{event}", "person": "{person}"},
            "secret": False,
            "required": False,
            "hidden": False,
        },
        {
            "key": "headers",
            "type": "dictionary",
            "label": "Headers",
            "secret": False,
            "required": False,
            "default": {"Content-Type": "application/json"},
            "hidden": False,
        },
        {
            "key": "debug",
            "type": "boolean",
            "label": "Log responses",
            "description": "Logs the response of http calls for debugging.",
            "secret": False,
            "required": False,
            "default": False,
            "hidden": False,
        },
    ],
    sub_templates=[
        HogFunctionSubTemplate(
            id="early-access-feature-enrollment",
            name="HTTP Webhook on feature enrollment",
            filters=SUB_TEMPLATE_COMMON["early-access-feature-enrollment"].filters,
        ),
        HogFunctionSubTemplate(
            id="survey-response",
            name="HTTP Webhook on survey response",
            filters=SUB_TEMPLATE_COMMON["survey-response"].filters,
        ),
        HogFunctionSubTemplate(
            id="activity-log",
            name="HTTP Webhook on team activity",
            filters=SUB_TEMPLATE_COMMON["activity-log"].filters,
            type="internal_destination",
        ),
    ],
)
