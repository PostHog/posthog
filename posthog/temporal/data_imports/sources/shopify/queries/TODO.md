# Shopify GraphQL Queries - Implementation Tasks

## Overview

Create paginated GraphQL query files for all Shopify resources following the pattern established in `posthog/temporal/data_imports/sources/shopify/graphql/abandoned_checkouts.py`.

## Pattern to Follow

Each query should:

- Use the pagination structure: `query Paginated{Resource}($n: Int!, $cursor: String)`
- Include `nodes` with resource fields and `pageInfo` with `hasNextPage` and `endCursor`
- Reuse existing fragments from `posthog/temporal/data_imports/sources/shopify/graphql/fragments.py`:
    - `KV_FRAGMENT` - for key/value pairs
    - `MAILING_ADDRESS_FRAGMENT` - for address objects
    - `MONEY_V2_FRAGMENT` - for money objects

## Tasks

- [x] **AbandonedCheckouts** - [Documentation](https://shopify.dev/docs/api/admin-graphql/latest/objects/abandonedcheckout)
- [x] **Articles** - [Documentation](https://shopify.dev/docs/api/admin-graphql/latest/objects/article)
- [ ] **Blogs** - [Documentation](https://shopify.dev/docs/api/admin-graphql/latest/objects/blog)
- [ ] **Collections** - [Documentation](https://shopify.dev/docs/api/admin-graphql/latest/objects/collection)
- [ ] **Collects** - [Documentation](https://shopify.dev/docs/api/admin-graphql/latest/objects/collect)
- [ ] **Countries** - [Documentation](https://shopify.dev/docs/api/admin-graphql/latest/objects/country)
- [ ] **CustomCollections** - [Documentation](https://shopify.dev/docs/api/admin-graphql/latest/objects/collection)
- [ ] **CustomerAddress** - [Documentation](https://shopify.dev/docs/api/admin-graphql/latest/objects/mailingaddress)
- [ ] **CustomerJourneySummary** - [Documentation](https://shopify.dev/docs/api/admin-graphql/latest/objects/customerjourneysummary)
- [ ] **Customers** - [Documentation](https://shopify.dev/docs/api/admin-graphql/latest/objects/customer)
- [ ] **DiscountCodes** - [Documentation](https://shopify.dev/docs/api/admin-graphql/latest/objects/priceruleuserror)
- [ ] **Disputes** - [Documentation](https://shopify.dev/docs/api/admin-graphql/latest/objects/shopifypaymentsdispute)
- [ ] **DraftOrders** - [Documentation](https://shopify.dev/docs/api/admin-graphql/latest/objects/draftorder)
- [ ] **FulfillmentOrders** - [Documentation](https://shopify.dev/docs/api/admin-graphql/latest/objects/fulfillmentorder)
- [ ] **Fulfillments** - [Documentation](https://shopify.dev/docs/api/admin-graphql/latest/objects/fulfillment)
- [ ] **InventoryItems** - [Documentation](https://shopify.dev/docs/api/admin-graphql/latest/objects/inventoryitem)
- [ ] **InventoryLevels** - [Documentation](https://shopify.dev/docs/api/admin-graphql/latest/objects/inventorylevel)
- [ ] **Locations** - [Documentation](https://shopify.dev/docs/api/admin-graphql/latest/objects/location)
- [ ] **MetafieldArticles** - [Documentation](https://shopify.dev/docs/api/admin-graphql/latest/objects/metafield)
- [ ] **MetafieldBlogs** - [Documentation](https://shopify.dev/docs/api/admin-graphql/latest/objects/metafield)
- [ ] **MetafieldCollections** - [Documentation](https://shopify.dev/docs/api/admin-graphql/latest/objects/metafield)
- [ ] **MetafieldCustomers** - [Documentation](https://shopify.dev/docs/api/admin-graphql/latest/objects/metafield)
- [ ] **MetafieldDraftOrders** - [Documentation](https://shopify.dev/docs/api/admin-graphql/latest/objects/metafield)
- [ ] **MetafieldLocations** - [Documentation](https://shopify.dev/docs/api/admin-graphql/latest/objects/metafield)
- [ ] **MetafieldOrders** - [Documentation](https://shopify.dev/docs/api/admin-graphql/latest/objects/metafield)
- [ ] **MetafieldPages** - [Documentation](https://shopify.dev/docs/api/admin-graphql/latest/objects/metafield)
- [ ] **MetafieldProductImages** - [Documentation](https://shopify.dev/docs/api/admin-graphql/latest/objects/metafield)
- [ ] **MetafieldProductVariants** - [Documentation](https://shopify.dev/docs/api/admin-graphql/latest/objects/metafield)
- [ ] **MetafieldProducts** - [Documentation](https://shopify.dev/docs/api/admin-graphql/latest/objects/metafield)
- [ ] **MetafieldShops** - [Documentation](https://shopify.dev/docs/api/admin-graphql/latest/objects/metafield)
- [ ] **MetafieldSmartCollections** - [Documentation](https://shopify.dev/docs/api/admin-graphql/latest/objects/metafield)
- [ ] **OrderAgreements** - [Documentation](https://shopify.dev/docs/api/admin-graphql/latest/objects/salesagreement)
- [ ] **OrderRefunds** - [Documentation](https://shopify.dev/docs/api/admin-graphql/latest/objects/refund)
- [ ] **OrderRisks** - [Documentation](https://shopify.dev/docs/api/admin-graphql/latest/objects/orderrisk)
- [ ] **Orders** - [Documentation](https://shopify.dev/docs/api/admin-graphql/latest/objects/order)
- [ ] **Pages** - [Documentation](https://shopify.dev/docs/api/admin-graphql/latest/objects/page)
- [ ] **PriceRules** - [Documentation](https://shopify.dev/docs/api/admin-graphql/latest/objects/pricerule)
- [ ] **ProductImages** - [Documentation](https://shopify.dev/docs/api/admin-graphql/latest/objects/image)
- [ ] **ProductVariants** - [Documentation](https://shopify.dev/docs/api/admin-graphql/latest/objects/productvariant)
- [ ] **Products** - [Documentation](https://shopify.dev/docs/api/admin-graphql/latest/objects/product)
- [ ] **ProfileLocationGroups** - [Documentation](https://shopify.dev/docs/api/admin-graphql/latest/objects/deliveryprofilelocationgroup)
- [ ] **Shop** - [Documentation](https://shopify.dev/docs/api/admin-graphql/latest/objects/shop) _(Note: May be single object, not paginated)_
- [ ] **SmartCollections** - [Documentation](https://shopify.dev/docs/api/admin-graphql/latest/objects/collection)
- [ ] **TenderTransactions** - [Documentation](https://shopify.dev/docs/api/admin-graphql/latest/objects/tendertransaction)
- [ ] **Transactions** - [Documentation](https://shopify.dev/docs/api/admin-graphql/latest/objects/ordertransaction)

## Special Notes

- **Metafield resources**: All metafield resources reference the same Metafield object type but need different query entry points based on their parent resource
- **Collections**: CustomCollections and SmartCollections both map to the Collection object type
- **Shop**: Likely a single object query rather than a paginated list
- **Object name mappings**: Some resources use different GraphQL object names (e.g., Disputes → ShopifyPaymentsDispute, OrderAgreements → SalesAgreement, Transactions → OrderTransaction)

## Implementation Guidelines

1. Create each file in `posthog/temporal/data_imports/sources/shopify/graphql/`
2. File naming: `{resource_name_snake_case}.py` (e.g., `balance_transactions.py`)
3. Verify the exact GraphQL query name and fields in the Shopify documentation before implementing
4. Consider nested pagination limits (e.g., the 250 limit for line items in abandoned checkouts)
5. Add new fragments to `fragments.py` if common patterns emerge
