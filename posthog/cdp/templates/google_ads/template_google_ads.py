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
        'Content-Type': 'application/json',
        'developer-token': inputs.developerToken
    },
    'body': {
        'conversions': [
            {
                'gclid': inputs.gclid,
                'conversionAction': f'customers/{inputs.customerId}/conversionActions/{inputs.conversionActionId}',
                'conversionDateTime': inputs.conversionDateTime
            }
        ],
        'partialFailure': true,
        'validateOnly': true
    }
})

if (res.status >= 400) {
    print('Error from googleads.googleapis.com api:', res.status, res.body)
}

""".strip(),
    inputs_schema=[
        {
            "key": "oauth",
            "type": "integration",
            "integration": "google-ads",
            "label": "Google Ads account",
            "secret": False,
            "required": True,
        },
        {
            "key": "developerToken",
            "type": "string",
            "label": "Developer token",
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
