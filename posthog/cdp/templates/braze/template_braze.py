from posthog.cdp.templates.hog_function_template import HogFunctionTemplate


template: HogFunctionTemplate = HogFunctionTemplate(
    status="beta",
    id="template-braze",
    name="Send events to Braze",
    description="Send events to Braze",
    icon_url="/static/services/braze.png",
    hog="""
let getEndpoint := () -> {
  'US-01': 'https://rest.iad-01.braze.com',
  'US-02': 'https://rest.iad-02.braze.com',
  'US-03': 'https://rest.iad-03.braze.com',
  'US-04': 'https://rest.iad-04.braze.com',
  'US-05': 'https://rest.iad-05.braze.com',
  'US-06': 'https://rest.iad-06.braze.com',
  'US-08': 'https://rest.iad-08.braze.com',
  'EU-01': 'https://rest.fra-01.braze.eu',
  'EU-02': 'https://rest.fra-02.braze.eu',
}[inputs.brazeEndpoint]

let getPayload := () -> [{
  'attributes': inputs.attributes,
  'events': [inputs.event]
}]

let res := fetch(f'{getEndpoint()}/users/track', {
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
                {"label": "US-01", "value": "US-01"},
                {"label": "US-02", "value": "US-02"},
                {"label": "US-03", "value": "US-03"},
                {"label": "US-04", "value": "US-04"},
                {"label": "US-05", "value": "US-05"},
                {"label": "US-06", "value": "US-06"},
                {"label": "US-08", "value": "US-08"},
                {"label": "EU-01", "value": "EU-01"},
                {"label": "EU-02", "value": "EU-02"},
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
            "label": "Event to send",
            "default": {
                "properties": "{event.properties}",
                "external_id": "{event.distinct_id}",
                "name": "{event.name}",
                "time": "{event.timestamp}",
            },
            "secret": False,
            "required": True,
        },
    ],
)
