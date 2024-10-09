from posthog.cdp.templates.hog_function_template import HogFunctionTemplate

template: HogFunctionTemplate = HogFunctionTemplate(
    status="alpha",
    id="template-google-ads",
    name="Google Ads Conversions",
    description="Send conversion events to Google Ads",
    icon_url="/static/services/google-ads.png",
    category=["Advertisement"],
    hog="""
let res := fetch(f'https://googleads.googleapis.com/v17/customers/{inputs.customerId}:uploadClickConversions', {
    'method': 'POST',
    'headers': {
        'Authorization': f'Bearer {inputs.auth.access_token}',
        'Content-Type': 'application/json'
    },
    'body': {
        'conversions': [
            {
                'gclid': inputs.gclid,
                'conversionAction': inputs.conversionActionId,
                'conversionDateTime': '2024-09-09 15:32:45-8:00'
            }
        ],
        'debugEnabled': true,
        'partialFailure': true
    }
})

if (res.status >= 400) {
    print('Error from googleads.googleapis.com api:', res.status, res.body)
}

""".strip(),
    inputs_schema=[
        {
            "key": "auth",
            "type": "integration",
            "integration": "google-ads",
            "label": "Google Cloud service account",
            "secret": False,
            "required": True,
        },
        {
            "key": "customerId",
            "type": "string",
            "label": "Customer ID",
            "secret": False,
            "required": True,
        },
        {
            "key": "conversionActionId",
            "type": "string",
            "label": "Conversion action ID",
            "secret": False,
            "required": True,
        },
        {
            "key": "gclid",
            "type": "string",
            "label": "Google Click ID (gclid)",
            "default": "{person.gclid}",
            "secret": False,
            "required": True,
        },
        {
            "key": "conversionDateTime",
            "type": "string",
            "label": "Conversion Date Time",
            "default": "{event.timestamp}",
            "secret": False,
            "required": True,
        },
    ],
    filters={
        "events": [],
        "actions": [],
        "filter_test_accounts": True,
    },
)
