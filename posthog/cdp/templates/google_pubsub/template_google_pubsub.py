from posthog.cdp.templates.hog_function_template import HogFunctionTemplate


template: HogFunctionTemplate = HogFunctionTemplate(
    status="beta",
    id="template-google-pubsub",
    name="Google PubSub",
    description="Send data to a Google PubSub topic",
    icon_url="/static/services/google-cloud.png",
    hog="""
let headers := {
    'Authorization': f'Bearer {inputs.oauth.access_token}',
    'Content-Type': 'application/json'
}

let res := fetch(f'https://pubsub.googleapis.com/v1/{inputs.topicName}:publish', {
  'method': 'POST',
  'headers': headers,
  'body': {
    'properties': properties
  }
})

if (res.status >= 200 and res.status < 300) {
  print('Event sent successfully!')
} else {
  print('Error sending event:', res.status, res.body)
}
""".strip(),
    inputs_schema=[
        {
            "key": "oauth",
            "type": "integration",
            "integration": "gcloud",
            "label": "Google Cloud service account",
            "secret": False,
            "required": True,
        },
        {
            "key": "topicName",
            "type": "string",
            "label": "Topic name",
            "secret": False,
            "required": True,
        },
        {
            "key": "payload",
            "type": "json",
            "label": "Message Payload",
            "default": {"event": "{event}", "person": "{person}"},
            "secret": False,
            "required": False,
        },
    ],
)
