from .fragments import KV_FRAGMENT, MAILING_ADDRESS_FRAGMENT, MONEY_V2_FRAGMENT

# NOTE: 250 is the max allowable query size for line items
ABANDONED_CHECKOUTS_QUERY = f"""
query PaginatedAbandonedCheckouts($pageSize: Int!, $cursor: String) {{
    abandonedCheckouts(first: $pageSize, after: $cursor) {{
        nodes {{
            abandonedCheckoutUrl
            billingAddress {MAILING_ADDRESS_FRAGMENT}
            completedAt
            createdAt
            customAttributes {KV_FRAGMENT}
            customer {{
                addresses {MAILING_ADDRESS_FRAGMENT}
                amountSpent {{
                    amount
                    currencyCode
                }}
                createdAt
                defaultAddress {MAILING_ADDRESS_FRAGMENT}
                defaultEmailAddress {{
                    emailAddress
                    marketingOptInLevel
                    marketingState
                    marketingUpdatedAt
                    openTrackingLevel
                    validFormat
                }}
                defaultPhoneNumber {{
                    marketingCollectedFrom
                    marketingOptInLevel
                    marketingState
                    marketingUpdatedAt
                    phoneNumber
                }}
                displayName
                firstName
                id
                lastName
                lastOrder {{
                    id
                    name
                }}
                legacyResourceId
                lifetimeDuration
                locale
                multipassIdentifier
                note
                numberOfOrders
                productSubscriberStatus
                state
                statistics {{
                    predictedSpendTier
                    rfmGroup
                }}
                tags
                taxExempt
                taxExemptions
                updatedAt
                verifiedEmail
            }}
            discountCodes
            id
            lineItems(first: 250) {{
                nodes {{
                    customAttributes {KV_FRAGMENT}
                    discountedTotalPriceSet {MONEY_V2_FRAGMENT}
                    discountedTotalPriceWithCodeDiscount {MONEY_V2_FRAGMENT}
                    discountedUnitPriceSet {MONEY_V2_FRAGMENT}
                    discountedUnitPriceWithCodeDiscount {MONEY_V2_FRAGMENT}
                    id
                    originalUnitPriceSet {MONEY_V2_FRAGMENT}
                    originalTotalPriceSet {MONEY_V2_FRAGMENT}
                    product {{
                        id
                        vendor
                    }}
                    quantity
                    sku
                    title
                    variant {{
                        id
                        title
                    }}
                }}
            }}
            name
            note
            shippingAddress {MAILING_ADDRESS_FRAGMENT}
            subtotalPriceSet {MONEY_V2_FRAGMENT}
            taxesIncluded
            totalDiscountSet {MONEY_V2_FRAGMENT}
            totalDutiesSet {MONEY_V2_FRAGMENT}
            totalLineItemsPriceSet {MONEY_V2_FRAGMENT}
            totalPriceSet {MONEY_V2_FRAGMENT}
            totalTaxSet {MONEY_V2_FRAGMENT}
            updatedAt
        }}
        pageInfo {{
            hasNextPage
            endCursor
        }}
    }}
}}"""
