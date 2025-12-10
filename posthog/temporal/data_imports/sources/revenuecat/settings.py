from products.data_warehouse.backend.types import IncrementalField, IncrementalFieldType

REVENUECAT_API_BASE_URL = "https://api.revenuecat.com/v2"
DEFAULT_LIMIT = 100

TIMESTAMP_FIELDS = ["first_seen_at", "last_seen_at", "updated_at", "created_at", "expires_at", "purchase_date"]

REVENUECAT_ENDPOINTS = [
    "Apps",
    "CustomerActiveEntitlements",
    "CustomerAliases",
    "CustomerPurchases",
    "CustomerSubscriptions",
    "Customers",
    "EntitlementProducts",
    "Entitlements",
    "OfferingPackages",
    "Offerings",
    "Products",
]

INCREMENTAL_ENDPOINTS = {
    "Apps",
    "Customers",
    "Entitlements",
    "Offerings",
    "Products",
}

_ID_INCREMENTAL_FIELD: list[IncrementalField] = [
    {
        "label": "id",
        "type": IncrementalFieldType.String,
        "field": "id",
        "field_type": IncrementalFieldType.String,
    }
]

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "Apps": _ID_INCREMENTAL_FIELD,
    "Customers": _ID_INCREMENTAL_FIELD,
    "Entitlements": _ID_INCREMENTAL_FIELD,
    "Offerings": _ID_INCREMENTAL_FIELD,
    "Products": _ID_INCREMENTAL_FIELD,
}
