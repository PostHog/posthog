from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="stable",
    free=True,
    type="destination",
    id="template-zapier",
    name="Zapier",
    description="Trigger Zaps in Zapier based on PostHog events. NOTE: Typically this is created from within Zapier using the PostHog app there.",
    icon_url="/static/services/zapier.png",
    category=["Custom"],
    code_language="hog",
    code="""
let hook_path := inputs.hook;
let prefix := 'https://hooks.zapier.com/';
// Remove the prefix if it exists
if (position(hook_path, prefix) == 1) {
  hook_path := replaceOne(hook_path, prefix, '');
}

// Remove leading slash if present to avoid double slashes
if (position(hook_path, '/') == 1) {
  hook_path := replaceOne(hook_path, '/', '');
}

let res := fetch(f'https://hooks.zapier.com/{hook_path}', {
  'method': 'POST',
  'body': inputs.body
});

if (inputs.debug) {
  print('Response', res.status, res.body);
}

""".strip(),
    inputs_schema=[
        {
            "key": "hook",
            "type": "string",
            "label": "Zapier hook path",
            "description": "Your Zapier webhook URL or just the path. You can create your own or use our native Zapier integration https://zapier.com/apps/posthog/integrations",
            "secret": False,
            "required": True,
            "hidden": False,
        },
        {
            "key": "body",
            "type": "json",
            "label": "JSON Body",
            "default": {
                "hook": {
                    "id": "{source.url}",
                    "event": "{event}",
                    "target": "https://hooks.zapier.com",
                },
                "data": {
                    "eventUuid": "{event.uuid}",
                    "event": "{event.event}",
                    "teamId": "{project.id}",
                    "distinctId": "{event.distinct_id}",
                    "properties": "{event.properties}",
                    "elementsChain": "{event.elementsChain}",
                    "timestamp": "{event.timestamp}",
                    "person": {"uuid": "{person.id}", "properties": "{person.properties}"},
                },
            },
            "secret": False,
            "required": False,
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
)
