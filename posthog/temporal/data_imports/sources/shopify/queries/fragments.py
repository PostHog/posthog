COUNT_FRAGMENT = """{
    count
    precision
}"""

EMAIL_ADDRESS_FRAGMENT = """{
    emailAddress
    marketingOptInLevel
    marketingState
    marketingUpdatedAt
    openTrackingLevel
    validFormat
}"""

KV_FRAGMENT = """{
    key
    value
}"""

MAILING_ADDRESS_FRAGMENT = """{
    address1
    address2
    city
    company
    coordinatesValidated
    country
    countryCodeV2
    firstName
    formatted
    formattedArea
    id
    lastName
    latitude
    longitude
    name
    phone
    province
    provinceCode
    timeZone
    validationResultSummary
    zip
}"""

METAFIELD_CONNECTIONS_FRAGMENT = """{
    nodes {
        compareDigest
        createdAt
        id
        jsonValue
        key
        namespace
        type
        updatedAt
        value
    }
}"""


MONEY_V2_FRAGMENT = """{
    amount
    currencyCode
}"""

MONEY_BAG_FRAGMENT = f"""{{
    presentmentMoney {MONEY_V2_FRAGMENT}
    shopMoney {MONEY_V2_FRAGMENT}
}}"""

PHONE_NUMBER_FRAGMENT = """{
    marketingCollectedFrom
    marketingOptInLevel
    marketingState
    marketingUpdatedAt
    phoneNumber
}"""
