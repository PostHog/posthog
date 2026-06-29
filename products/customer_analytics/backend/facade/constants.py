"""Facade re-exports for customer_analytics constants.

These constants are pure, framework-free values (no heavy imports), reached
cross-boundary only through the facade. The internal ``backend.constants`` module
stays as the source of truth.
"""

from products.customer_analytics.backend.constants import (
    ACCOUNT_ASSIGNMENT_ROLE_FIELDS,
    BILLING_SPEND_INSIGHT_SHORT_IDS,
    BILLING_USAGE_INSIGHT_SHORT_IDS,
    CUSTOM_PROPERTY_DISPLAY_TYPE_CHOICES,
    CUSTOMER_ANALYTICS_CSP_FLAG,
    DEFAULT_ACTIVITY_EVENT,
)

__all__ = [
    "ACCOUNT_ASSIGNMENT_ROLE_FIELDS",
    "BILLING_SPEND_INSIGHT_SHORT_IDS",
    "BILLING_USAGE_INSIGHT_SHORT_IDS",
    "CUSTOM_PROPERTY_DISPLAY_TYPE_CHOICES",
    "CUSTOMER_ANALYTICS_CSP_FLAG",
    "DEFAULT_ACTIVITY_EVENT",
]
