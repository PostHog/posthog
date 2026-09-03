"""Test-support facade for customer_analytics.

Outside test suites plant accounts and their related rows (custom properties,
relationships, feature requests, meetings, channel summaries) through this module so
they never import the product's models or its test factories directly.
"""

from products.customer_analytics.backend.test.factories import (
    create_account,
    create_account_channel_summary,
    create_account_relationship,
    create_account_relationship_definition,
    create_custom_property_definition,
    create_custom_property_value,
    create_feature_request,
    create_feature_request_account_link,
    create_feature_request_evidence,
    create_feature_request_history,
    create_feature_request_product_area,
    create_feature_request_product_area_link,
    create_meeting,
)

__all__ = [
    "create_account",
    "create_account_channel_summary",
    "create_account_relationship",
    "create_account_relationship_definition",
    "create_custom_property_definition",
    "create_custom_property_value",
    "create_feature_request",
    "create_feature_request_account_link",
    "create_feature_request_evidence",
    "create_feature_request_history",
    "create_feature_request_product_area",
    "create_feature_request_product_area_link",
    "create_meeting",
]
