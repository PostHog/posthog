from posthog.cdp.templates.hog_function_template import HogFunctionTemplate


template: HogFunctionTemplate = HogFunctionTemplate(
    status="alpha",
    type="destination",
    id="template-tiktok-ads",
    name="Tiktok Ads Conversions",
    description="Send conversion events to Tiktok Ads",
    icon_url="/static/services/tiktok.png",
    category=["Advertisement"],
    hog="""
let res := fetch(f'https://ads.tiktok.com/TODO', {
    'method': 'POST',
    'headers': {
        'Authorization': f'Bearer {inputs.oauth.access_token}',
        'Content-Type': 'application/json'
    },
    'body': body
})

if (res.status >= 400) {
    throw Error(f'Error from ads.tiktok.com (status {res.status}): {res.body}')
}
""".strip(),
    inputs_schema=[
        {
            "key": "accessToken",
            "type": "string",
            "label": "Tiktok access token",
            "description": "TODO",
            "secret": True,
            "required": True,
        }
    ],
    filters={
        "events": [],
        "actions": [],
        "filter_test_accounts": True,
        "mappings": [
            {
                "name": "Paid conversion",
            }
        ],
    },
)
