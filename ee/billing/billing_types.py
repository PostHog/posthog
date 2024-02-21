from decimal import Decimal
from typing import Dict, List, Optional, TypedDict

from posthog.constants import AvailableFeature


class Tier(TypedDict):
    flat_amount_usd: Decimal
    unit_amount_usd: Decimal
    current_amount_usd: Decimal
    up_to: Optional[int]


class CustomerProduct(TypedDict):
    name: str
    description: str
    price_description: Optional[str]
    image_url: Optional[str]
    type: str
    free_allocation: int
    tiers: List[Tier]
    tiered: bool
    unit_amount_usd: Optional[Decimal]
    current_amount_usd: Decimal
    current_usage: int
    usage_limit: Optional[int]
    has_exceeded_limit: bool
    percentage_usage: float
    projected_usage: int
    projected_amount: Decimal


class LicenseInfo(TypedDict):
    type: str


class BillingPeriod(TypedDict):
    current_period_start: str
    current_period_end: str
    interval: str


class UsageSummary(TypedDict):
    limit: Optional[int]
    usage: Optional[int]


class CustomerInfo(TypedDict):
    customer_id: Optional[str]
    deactivated: bool
    has_active_subscription: bool
    billing_period: BillingPeriod
    available_features: List[AvailableFeature]
    current_total_amount_usd: Optional[str]
    current_total_amount_usd_after_discount: Optional[str]
    products: Optional[List[CustomerProduct]]
    custom_limits_usd: Optional[Dict[str, str]]
    usage_summary: Optional[Dict[str, Dict[str, Optional[int]]]]
    free_trial_until: Optional[str]
    discount_percent: Optional[int]
    discount_amount_usd: Optional[str]
    highest_paid_bill: int
    trust_score_overwritten: bool


class BillingStatus(TypedDict):
    license: LicenseInfo
    customer: CustomerInfo
