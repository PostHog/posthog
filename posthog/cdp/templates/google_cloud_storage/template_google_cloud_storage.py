from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="beta",
    free=False,
    type="destination",
    id="template-google-cloud-storage",
    name="Google Cloud Storage",
    description="Send data to GCS. This creates a file per event.",
    icon_url="/static/services/google-cloud-storage.png",
    category=["Custom"],
    code_language="hog",
    code="""
let res := fetch(f'https://storage.googleapis.com/upload/storage/v1/b/{encodeURLComponent(inputs.bucketName)}/o?uploadType=media&name={encodeURLComponent(inputs.filename)}', {
  'method': 'POST',
  'headers': {
    'Authorization': f'Bearer {inputs.auth.access_token}',
    'Content-Type': 'application/json'
  },
  'body': inputs.payload
})

if (res.status >= 200 and res.status < 300) {
  print('Event sent successfully!')
} else {
  throw Error('Error sending event', res)
}
""".strip(),
    inputs_schema=[
        {
            "key": "auth",
            "type": "integration",
            "integration": "google-cloud-storage",
            "label": "Google Cloud service account",
            "secret": False,
            "required": True,
        },
        {
            "key": "bucketName",
            "type": "string",
            "label": "Bucket name",
            "secret": False,
            "required": True,
        },
        {
            "key": "filename",
            "type": "string",
            "label": "Filename",
            "default": "{toDate(event.timestamp)}/{event.timestamp}-{event.uuid}.json",
            "secret": False,
            "required": True,
        },
        {
            "key": "payload",
            "type": "string",
            "label": "File contents",
            "default": "{jsonStringify({ 'event': event, 'person': person })}",
            "secret": False,
            "required": True,
        },
    ],
)
