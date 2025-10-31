from .fragments import COUNT_FRAGMENT, MONEY_V2_FRAGMENT, NODE_CONNECTION_ID_FRAGMENT

DISCOUNT_NODES_SORTKEY = "UPDATED_AT"

# NOTE: 250 is the max allowable query size for nested connections
DISCOUNT_NODES_QUERY = f"""
query PaginatedDiscountCodes($pageSize: Int!, $cursor: String, $query: String) {{
    discountNodes(
        first: $pageSize, after: $cursor, sortKey: {DISCOUNT_NODES_SORTKEY},
        query: $query
    ) {{
        nodes {{
            id
            discount {{
                ... on DiscountCodeBasic {{
                    title
                    summary
                    status
                    createdAt
                    updatedAt
                    startsAt
                    endsAt
                    usageLimit
                    appliesOncePerCustomer
                    asyncUsageCount
                    hasTimelineComment
                    recurringCycleLimit
                    codesCount {COUNT_FRAGMENT}
                    totalSales {MONEY_V2_FRAGMENT}
                    codes(first: 250) {{
                        nodes {{
                            id
                            code
                        }}
                    }}
                    combinesWith {{
                        orderDiscounts
                        productDiscounts
                        shippingDiscounts
                    }}
                    customerGets {{
                        appliesOnOneTimePurchase
                        appliesOnSubscription
                        items {{
                            ... on AllDiscountItems {{
                                allItems
                            }}
                            ... on DiscountProducts {{
                                productVariants(first: 250) {NODE_CONNECTION_ID_FRAGMENT}
                                products(first: 250) {NODE_CONNECTION_ID_FRAGMENT}
                            }}
                            ... on DiscountCollections {{
                                collections(first: 250) {NODE_CONNECTION_ID_FRAGMENT}
                            }}
                        }}
                        value {{
                            ... on DiscountAmount {{
                                amount {MONEY_V2_FRAGMENT}
                                appliesOnEachItem
                            }}
                            ... on DiscountPercentage {{
                                percentage
                            }}
                        }}
                    }}
                    minimumRequirement {{
                        ... on DiscountMinimumQuantity {{
                            greaterThanOrEqualToQuantity
                        }}
                        ... on DiscountMinimumSubtotal {{
                            greaterThanOrEqualToSubtotal {MONEY_V2_FRAGMENT}
                        }}
                    }}
                    shareableUrls {{
                        targetItemImage {{
                            url
                        }}
                        targetType
                        title
                        url
                    }}
                }}
                ... on DiscountCodeBxgy {{
                    title
                    summary
                    status
                    createdAt
                    updatedAt
                    startsAt
                    endsAt
                    usageLimit
                    appliesOncePerCustomer
                    asyncUsageCount
                    hasTimelineComment
                    codesCount {COUNT_FRAGMENT}
                    totalSales {MONEY_V2_FRAGMENT}
                    codes(first: 250) {{
                        nodes {{
                            id
                            code
                        }}
                    }}
                    combinesWith {{
                        orderDiscounts
                        productDiscounts
                        shippingDiscounts
                    }}
                    customerBuys {{
                        items {{
                            ... on AllDiscountItems {{
                                allItems
                            }}
                            ... on DiscountProducts {{
                                productVariants(first: 250) {NODE_CONNECTION_ID_FRAGMENT}
                                products(first: 250) {NODE_CONNECTION_ID_FRAGMENT}
                            }}
                            ... on DiscountCollections {{
                                collections(first: 250) {NODE_CONNECTION_ID_FRAGMENT}
                            }}
                        }}
                        value {{
                            ... on DiscountQuantity {{
                                quantity
                            }}
                            ... on DiscountPurchaseAmount {{
                                amount
                            }}
                        }}
                    }}
                    customerGets {{
                        appliesOnOneTimePurchase
                        appliesOnSubscription
                        items {{
                            ... on AllDiscountItems {{
                                allItems
                            }}
                            ... on DiscountProducts {{
                                productVariants(first: 250) {NODE_CONNECTION_ID_FRAGMENT}
                                products(first: 250) {NODE_CONNECTION_ID_FRAGMENT}
                            }}
                            ... on DiscountCollections {{
                                collections(first: 250) {NODE_CONNECTION_ID_FRAGMENT}
                            }}
                        }}
                        value {{
                            ... on DiscountAmount {{
                                amount {MONEY_V2_FRAGMENT}
                                appliesOnEachItem
                            }}
                            ... on DiscountPercentage {{
                                percentage
                            }}
                        }}
                    }}
                    usesPerOrderLimit
                }}
                ... on DiscountCodeFreeShipping {{
                    title
                    summary
                    status
                    createdAt
                    updatedAt
                    startsAt
                    endsAt
                    usageLimit
                    appliesOncePerCustomer
                    asyncUsageCount
                    hasTimelineComment
                    recurringCycleLimit
                    codesCount {COUNT_FRAGMENT}
                    totalSales {MONEY_V2_FRAGMENT}
                    codes(first: 250) {{
                        nodes {{
                            id
                            code
                        }}
                    }}
                    combinesWith {{
                        orderDiscounts
                        productDiscounts
                        shippingDiscounts
                    }}
                    destinationSelection {{
                        ... on DiscountCountries {{
                            countries
                            includeRestOfWorld
                        }}
                        ... on DiscountCountryAll {{
                            allCountries
                        }}
                    }}
                    maximumShippingPrice {MONEY_V2_FRAGMENT}
                    minimumRequirement {{
                        ... on DiscountMinimumQuantity {{
                            greaterThanOrEqualToQuantity
                        }}
                        ... on DiscountMinimumSubtotal {{
                            greaterThanOrEqualToSubtotal {MONEY_V2_FRAGMENT}
                        }}
                    }}
                }}
                ... on DiscountCodeApp {{
                    title
                    status
                    createdAt
                    updatedAt
                    startsAt
                    endsAt
                    discountClasses
                    appliesOncePerCustomer
                    asyncUsageCount
                    codesCount {COUNT_FRAGMENT}
                    totalSales {MONEY_V2_FRAGMENT}
                    codes(first: 250) {{
                        nodes {{
                            id
                            code
                        }}
                    }}
                    combinesWith {{
                        orderDiscounts
                        productDiscounts
                        shippingDiscounts
                    }}
                    appDiscountType {{
                        appKey
                        discountClasses
                        functionId
                        title
                    }}
                }}
            }}
        }}
        pageInfo {{
            hasNextPage
            endCursor
        }}
    }}
}}"""
