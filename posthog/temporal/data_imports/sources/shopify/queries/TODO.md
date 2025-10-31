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
- [x] **Blogs** - [Documentation](https://shopify.dev/docs/api/admin-graphql/latest/objects/blog)
- [x] **Collections** - [Documentation](https://shopify.dev/docs/api/admin-graphql/latest/objects/collection)
- [x] **Catalogs** - [Documentation](https://shopify.dev/docs/api/admin-graphql/latest/interfaces/catalog)
- [x] **Companies** - [Documentation](https://shopify.dev/docs/api/admin-graphql/latest/objects/company)
- [x] **Customers** - [Documentation](https://shopify.dev/docs/api/admin-graphql/latest/objects/customer)
- [ ] **DiscountCodes** - [Documentation](https://shopify.dev/docs/api/admin-graphql/latest/objects/priceruleuserror)
- [ ] **Disputes** - [Documentation](https://shopify.dev/docs/api/admin-graphql/latest/objects/shopifypaymentsdispute)
- [ ] **DraftOrders** - [Documentation](https://shopify.dev/docs/api/admin-graphql/latest/objects/draftorder)
- [ ] **InventoryItems** - [Documentation](https://shopify.dev/docs/api/admin-graphql/latest/objects/inventoryitem)
- [ ] **Locations** - [Documentation](https://shopify.dev/docs/api/admin-graphql/latest/objects/location)
- [ ] **Metafields** - [Documentation](https://shopify.dev/docs/api/admin-graphql/latest/objects/metafield)
- [ ] **Orders** - [Documentation](https://shopify.dev/docs/api/admin-graphql/latest/objects/order)
- [ ] **Pages** - [Documentation](https://shopify.dev/docs/api/admin-graphql/latest/objects/page)
- [ ] **Products** - [Documentation](https://shopify.dev/docs/api/admin-graphql/latest/objects/product)
- [ ] **Shop** - [Documentation](https://shopify.dev/docs/api/admin-graphql/latest/objects/shop) _(Note: May be single object, not paginated)_
- [ ] _SubscriptionContracts_ - [Documentation](https://shopify.dev/docs/api/admin-graphql/latest/objects/subscriptioncontract)

## Special Notes

- **Collections**: CustomCollections and SmartCollections both map to the Collection object type
- **Shop**: Likely a single object query rather than a paginated list

## Implementation Guidelines

1. Create each file in `posthog/temporal/data_imports/sources/shopify/graphql/`
2. File naming: `{resource_name_snake_case}.py` (e.g., `balance_transactions.py`)
3. Verify the exact GraphQL query name and fields in the Shopify documentation before implementing
4. Consider nested pagination limits (e.g., the 250 limit for line items in abandoned checkouts)
5. Add new fragments to `fragments.py` if common patterns emerge
