from posthog.cdp.templates.hog_function_template import (
    SUB_TEMPLATE_COMMON,
    HogFunctionMappingTemplate,
    HogFunctionSubTemplate,
    HogFunctionTemplate,
)

# NOTE: This is a pre-release template using mappings. We

template: HogFunctionTemplate = HogFunctionTemplate(
    status="alpha",
    free=False,
    type="destination",
    id="template-webhook-mappings",
    name="HTTP Webhook (mappings based)",
    description="Sends a webhook templated by the incoming event data",
    icon_url="/static/posthog-icon.svg",
    category=["Custom"],
    hog="""
let headers := {}

for (let key, value in inputs.headers) {
    headers[key] := value
}
if (inputs.additional_headers) {
  for (let key, value in inputs.additional_headers) {
    headers[key] := value
  }
}

let payload := {
  'headers': headers,
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
            "key": "headers",
            "type": "dictionary",
            "label": "Headers",
            "secret": False,
            "required": False,
            "default": {"Content-Type": "application/json"},
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
    mapping_templates=[
        HogFunctionMappingTemplate(
            name="Webhook",
            include_by_default=True,
            filters={"events": [{"id": "$pageview", "name": "Pageview", "type": "events"}]},
            inputs_schema=[
                {
                    "key": "body",
                    "type": "json",
                    "label": "JSON Body",
                    "default": {"event": "{event}", "person": "{person}"},
                    "secret": False,
                    "required": False,
                },
                {
                    "key": "additional_headers",
                    "type": "dictionary",
                    "label": "Additional headers",
                    "secret": False,
                    "required": False,
                    "default": {},
                },
            ],
        ),
    ],
)
