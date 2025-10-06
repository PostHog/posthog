from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="beta",
    free=False,
    type="destination",
    id="template-braze",
    name="Braze",
    description="Send events to Braze",
    icon_url="/static/services/braze.png",
    category=["Customer Success"],
    code_language="hog",
    code="""
let getPayload := () -> [{
  'attributes': inputs.attributes,
  'events': [inputs.event]
}]

let res := fetch(f'{inputs.brazeEndpoint}/users/track', {
  'method': 'POST',
  'headers': {
    'Authorization': f'Bearer {inputs.apiKey}',
    'Content-Type': 'application/json'
  },
  'body': getPayload()
})

if (res.status >= 200 and res.status < 300) {
  print('Event sent successfully!')
} else {
  throw Error(f'Error sending event: {res.status} {res.body}')
}
""".strip(),
    inputs_schema=[
        {
            "key": "brazeEndpoint",
            "type": "choice",
            "label": "Braze REST Endpoint",
            "description": "The endpoint identifier where your Braze instance is located, see the docs here: https://www.braze.com/docs/api/basics",
            "choices": [
                {"label": "US-01", "value": "https://rest.iad-01.braze.com"},
                {"label": "US-02", "value": "https://rest.iad-02.braze.com"},
                {"label": "US-03", "value": "https://rest.iad-03.braze.com"},
                {"label": "US-04", "value": "https://rest.iad-04.braze.com"},
                {"label": "US-05", "value": "https://rest.iad-05.braze.com"},
                {"label": "US-06", "value": "https://rest.iad-06.braze.com"},
                {"label": "US-07", "value": "https://rest.iad-07.braze.com"},
                {"label": "US-08", "value": "https://rest.iad-08.braze.com"},
                {"label": "US-10", "value": "https://rest.iad-10.braze.com"},
                {"label": "EU-01", "value": "https://rest.fra-01.braze.eu"},
                {"label": "EU-02", "value": "https://rest.fra-02.braze.eu"},
                {"label": "AU-01", "value": "https://rest.au-01.braze.com"},
            ],
            "default": "",
            "secret": False,
            "required": True,
        },
        {
            "key": "apiKey",
            "type": "string",
            "label": "Your Braze API Key",
            "description": "See the docs here: https://www.braze.com/docs/api/api_key/",
            "default": "",
            "secret": True,
            "required": True,
        },
        {
            "key": "attributes",
            "type": "json",
            "label": "Attributes to set",
            "default": {"email": "{person.properties.email}"},
            "secret": False,
            "required": True,
        },
        {
            "key": "event",
            "type": "json",
            "label": "Event payload",
            "default": {
                "properties": "{event.properties}",
                "external_id": "{event.distinct_id}",
                "name": "{event.event}",
                "time": "{event.timestamp}",
            },
            "secret": False,
            "required": True,
        },
    ],
)
