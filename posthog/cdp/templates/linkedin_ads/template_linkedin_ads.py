from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="hidden",
    free=False,
    type="destination",
    id="template-linkedin-ads",
    name="LinkedIn Ads Conversions",
    description="Send conversion events to LinkedIn Ads",
    icon_url="/static/services/linkedin.png",
    category=["Advertisement"],
    code_language="hog",
    code="""
let body := {
    'conversion': f'urn:lla:llaPartnerConversion:{inputs.conversionRuleId}',
    'conversionHappenedAt': inputs.conversionDateTime,
    'user': {
        'userIds': [],
        'userInfo': {}
     },
    'eventId' : inputs.eventId
}

if (not empty(inputs.conversionValue) or not empty(inputs.currencyCode)) {
    body.conversionValue := {}
}
if (not empty(inputs.currencyCode)) {
    body.conversionValue.currencyCode := inputs.currencyCode
}
if (not empty(inputs.conversionValue)) {
    body.conversionValue.amount := inputs.conversionValue
}

for (let key, value in inputs.userInfo) {
    if (not empty(value)) {
        body.user.userInfo[key] := value
    }
}

for (let key, value in inputs.userIds) {
    if (not empty(value)) {
        body.user.userIds := arrayPushBack(body.user.userIds, {'idType': key, 'idValue': value})
    }
}

let res := fetch('https://api.linkedin.com/rest/conversionEvents', {
    'method': 'POST',
    'headers': {
        'Authorization': f'Bearer {inputs.oauth.access_token}',
        'Content-Type': 'application/json',
        'LinkedIn-Version': '202409'
    },
    'body': body
})

if (res.status >= 400) {
    throw Error(f'Error from api.linkedin.com (status {res.status}): {res.body}')
}
""".strip(),
    inputs_schema=[
        {
            "key": "oauth",
            "type": "integration",
            "integration": "linkedin-ads",
            "label": "LinkedIn Ads account",
            "secret": False,
            "required": True,
        },
        {
            "key": "accountId",
            "type": "integration_field",
            "integration_key": "oauth",
            "integration_field": "linkedin_ads_account_id",
            "label": "Account ID",
            "description": "ID of your LinkedIn Ads Account. This should be 9-digits and in XXXXXXXXX format.",
            "secret": False,
            "required": True,
        },
        {
            "key": "conversionRuleId",
            "type": "integration_field",
            "integration_key": "oauth",
            "integration_field": "linkedin_ads_conversion_rule_id",
            "requires_field": "accountId",
            "label": "Conversion rule",
            "description": "The Conversion rule associated with this conversion.",
            "secret": False,
            "required": True,
        },
        {
            "key": "conversionDateTime",
            "type": "string",
            "label": "Conversion Date Time",
            "description": "The timestamp at which the conversion occurred in milliseconds. Must be after the click time.",
            "default": "{toUnixTimestampMilli(event.timestamp)}",
            "secret": False,
            "required": True,
        },
        {
            "key": "conversionValue",
            "type": "string",
            "label": "Conversion value",
            "description": "The value of the conversion for the advertiser in decimal string. (e.g. “100.05”).",
            "default": "",
            "secret": False,
            "required": False,
        },
        {
            "key": "currencyCode",
            "type": "string",
            "label": "Currency code",
            "description": "Currency associated with the conversion value. This is the ISO 4217 3-character currency code. For example: USD, EUR.",
            "default": "",
            "secret": False,
            "required": False,
        },
        {
            "key": "eventId",
            "type": "string",
            "label": "Event ID",
            "description": "ID of the event that triggered the conversion.",
            "default": "{event.uuid}",
            "secret": False,
            "required": True,
        },
        {
            "key": "userIds",
            "type": "dictionary",
            "label": "User ids",
            "description": "A map that contains user ids. See this page for options: https://learn.microsoft.com/en-us/linkedin/marketing/integrations/ads-reporting/conversions-api?view=li-lms-2024-03&tabs=curl#idtype",
            "default": {
                "SHA256_EMAIL": "{sha256Hex(person.properties.email)}",
                "LINKEDIN_FIRST_PARTY_ADS_TRACKING_UUID": "{person.properties.li_fat_id ?? person.properties.$initial_li_fat_id}",
            },
            "secret": False,
            "required": True,
        },
        {
            "key": "userInfo",
            "type": "dictionary",
            "label": "User information",
            "description": "A map that contains user information data. See this page for options: https://learn.microsoft.com/en-us/linkedin/marketing/integrations/ads-reporting/conversions-api?view=li-lms-2024-03&tabs=curl#userinfo",
            "default": {
                "firstName": "{person.properties.first_name}",
                "lastName": "{person.properties.last_name}",
                "title": "{person.properties.title}",
                "companyName": "{person.properties.company}",
                "countryCode": "{person.properties.$geoip_country_code}",
            },
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
