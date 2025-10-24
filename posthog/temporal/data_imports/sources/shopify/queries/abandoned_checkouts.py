from .fragments import KV_FRAGMENT, MAILING_ADDRESS_FRAGMENT, MONEY_BAG_FRAGMENT

ABANDONED_CHECKOUTS_SORTKEY = "CREATED_AT"

# NOTE: 250 is the max allowable query size for line items
ABANDONED_CHECKOUTS_QUERY = f"""
query PaginatedAbandonedCheckouts($pageSize: Int!, $cursor: String, $query: String) {{
    abandonedCheckouts(
        first: $pageSize, after: $cursor, sortKey: {ABANDONED_CHECKOUTS_SORTKEY},
        query: $query
    ) {{
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
                    discountedTotalPriceSet {MONEY_BAG_FRAGMENT}
                    discountedTotalPriceWithCodeDiscount {MONEY_BAG_FRAGMENT}
                    discountedUnitPriceSet {MONEY_BAG_FRAGMENT}
                    discountedUnitPriceWithCodeDiscount {MONEY_BAG_FRAGMENT}
                    id
                    originalUnitPriceSet {MONEY_BAG_FRAGMENT}
                    originalTotalPriceSet {MONEY_BAG_FRAGMENT}
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
            subtotalPriceSet {MONEY_BAG_FRAGMENT}
            taxesIncluded
            totalDiscountSet {MONEY_BAG_FRAGMENT}
            totalDutiesSet {MONEY_BAG_FRAGMENT}
            totalLineItemsPriceSet {MONEY_BAG_FRAGMENT}
            totalPriceSet {MONEY_BAG_FRAGMENT}
            totalTaxSet {MONEY_BAG_FRAGMENT}
            updatedAt
        }}
        pageInfo {{
            hasNextPage
            endCursor
        }}
    }}
}}"""
