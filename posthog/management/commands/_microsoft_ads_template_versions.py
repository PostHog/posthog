# Hog code of earlier Microsoft Ads template versions, copied verbatim. A destination whose saved code
# matches one of these was never edited, so the migration can replace its code with the current template.

MICROSOFT_ADS_CLICK_ID_ONLY = """
if (empty(inputs.microsoftClickId)) {
    print('Empty `microsoftClickId`. Skipping...')
    return
}

let userData := {
    'msclkid': inputs.microsoftClickId
}
if (not empty(inputs.email)) {
    userData.em := sha256Hex(lower(trim(inputs.email)))
}
if (not empty(inputs.phone)) {
    userData.ph := sha256Hex(lower(trim(inputs.phone)))
}

let conversion := {
    'eventType': 'custom',
    'eventName': inputs.eventName,
    'eventTime': inputs.eventTime,
    'userData': userData
}
if (not empty(inputs.eventId)) {
    conversion.eventId := inputs.eventId
}

let customData := {}
if (not empty(inputs.conversionValue)) {
    customData.value := toFloat(inputs.conversionValue)
}
if (not empty(inputs.currency)) {
    customData.currency := inputs.currency
}
if (length(keys(customData)) > 0) {
    conversion.customData := customData
}

let res := fetch(f'https://capi.uet.microsoft.com/v1/{inputs.tagId}/events', {
    'method': 'POST',
    'headers': {
        'Authorization': f'Bearer {inputs.apiToken}',
        'Content-Type': 'application/json'
    },
    'body': {
        'data': [conversion]
    }
})

if (res.status >= 400) {
    throw Error(f'Error from capi.uet.microsoft.com (status {res.status}): {res.body}')
}
"""

MICROSOFT_ADS_EMAIL_OR_PHONE = """
let userData := {}
if (not empty(inputs.microsoftClickId)) {
    userData.msclkid := inputs.microsoftClickId
}
if (not empty(inputs.email)) {
    userData.em := sha256Hex(lower(trim(inputs.email)))
}
if (not empty(inputs.phone)) {
    userData.ph := sha256Hex(lower(trim(inputs.phone)))
}
// Microsoft can only attribute a conversion if it carries at least one identifier
if (length(keys(userData)) == 0) {
    print('No `microsoftClickId`, `email` or `phone` to identify the user with. Skipping...')
    return
}

let conversion := {
    'eventType': 'custom',
    'eventName': inputs.eventName,
    'eventTime': inputs.eventTime,
    'userData': userData
}
if (not empty(inputs.eventId)) {
    conversion.eventId := inputs.eventId
}

let customData := {}
if (not empty(inputs.conversionValue)) {
    customData.value := toFloat(inputs.conversionValue)
}
if (not empty(inputs.currency)) {
    customData.currency := inputs.currency
}
if (length(keys(customData)) > 0) {
    conversion.customData := customData
}

let res := fetch(f'https://capi.uet.microsoft.com/v1/{inputs.tagId}/events', {
    'method': 'POST',
    'headers': {
        'Authorization': f'Bearer {inputs.apiToken}',
        'Content-Type': 'application/json'
    },
    'body': {
        'data': [conversion]
    }
})

if (res.status >= 400) {
    throw Error(f'Error from capi.uet.microsoft.com (status {res.status}): {res.body}')
}
"""
