from posthog.warehouse.types import IncrementalField


ENDPOINTS = ("User", "UserRole", "Lead", "Contact", "Campaign", "Product2", "Pricebook2", "PricebookEntry")

INCREMENTAL_ENDPOINTS = ()

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
