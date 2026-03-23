from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="stable",
    free=False,
    type="destination",
    id="template-trophy",
    name="Trophy",
    description="Sends events to a metric in Trophy",
    icon_url="/static/services/trophy.png",
    category=["Custom"],
    code_language="hog",
    code="""
let url := f'https://api.trophy.so/v1/metrics/{inputs.metric_key}/event'

let user := {
  'id': inputs.user_id
}
if (not empty(inputs.user_email)) {
  user.email := inputs.user_email
}
if (not empty(inputs.user_name)) {
  user.name := inputs.user_name
}
if (not empty(inputs.user_tz)) {
  user.tz := inputs.user_tz
}
if (not empty(inputs.user_attributes)) {
  user.attributes := inputs.user_attributes
}

let body := {
  'value': inputs.event_value,
  'user': user
}
if (not empty(inputs.event_attributes)) {
  body.attributes := inputs.event_attributes
}

let payload := {
  'headers': {
    'Content-Type': 'application/json',
    'X-API-KEY': inputs.api_key
  },
  'body': body,
  'method': 'POST'
}

if (inputs.debug) {
  print('Request', url, payload)
}

let res := fetch(url, payload);

if (inputs.debug) {
  print('Response', res.status, res.body);
}
if (res.status >= 400) {
    throw Error(f'Error from api.trophy.so (status {res.status}): {res.body}')
}
""".strip(),
    inputs_schema=[
        {
            "key": "api_key",
            "type": "string",
            "label": "Trophy API Key",
            "secret": True,
            "required": True,
            "description": "Create this at https://app.trophy.so/integration/api-keys",
        },
        {
            "key": "metric_key",
            "type": "string",
            "label": "Metric Key",
            "secret": False,
            "required": True,
            "description": "The key of the metric to send the event to.",
        },
        {
            "key": "user_id",
            "type": "string",
            "label": "User ID",
            "description": "Your internal user ID for the user.",
            "default": "{person.id}",
            "secret": False,
            "required": True,
        },
        {
            "key": "event_value",
            "type": "number",
            "label": "Event Value",
            "description": "The value of the event.",
            "default": 1,
            "secret": False,
            "required": True,
        },
        {
            "key": "user_email",
            "type": "string",
            "label": "User Email",
            "description": "The email of the user.",
            "default": "{person.properties.email}",
            "secret": False,
            "required": False,
        },
        {
            "key": "user_name",
            "type": "string",
            "label": "User Name",
            "description": "The name of the user.",
            "default": "{person.name}",
            "secret": False,
            "required": False,
        },
        {
            "key": "user_tz",
            "type": "string",
            "label": "User Timezone",
            "description": "The timezone of the user.",
            "secret": False,
            "required": False,
        },
        {
            "key": "user_attributes",
            "type": "dictionary",
            "label": "Custom User Attributes",
            "default": {},
            "secret": False,
            "required": False,
            "description": "Map PostHog user properties to Trophy user attributes. For more information on user attributes, see https://docs.trophy.so/platform/users#custom-user-attributes",
        },
        {
            "key": "event_attributes",
            "type": "dictionary",
            "label": "Custom Event Attributes",
            "default": {},
            "secret": False,
            "required": False,
            "description": "Map PostHog event properties to Trophy event attributes. For more information on event attributes, see https://docs.trophy.so/platform/events#custom-event-attributes",
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
)
