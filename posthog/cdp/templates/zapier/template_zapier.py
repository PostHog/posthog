from posthog.cdp.templates.hog_function_template import HogFunctionTemplate


template: HogFunctionTemplate = HogFunctionTemplate(
    status="free",
    type="destination",
    id="template-zapier",
    name="Zapier",
    description="Trigger Zaps in Zapier based on PostHog events.",
    icon_url="/static/services/zapier.png",
    category=["Custom"],
    hog="""
let res := fetch(f'https://hooks.zapier.com/{inputs.hook}', {
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
            "description": "The path of the Zapier webhook. You can create your own or use our native Zapier integration https://zapier.com/apps/posthog/integrations",
            "secret": False,
            "required": True,
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
