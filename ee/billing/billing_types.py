from decimal import Decimal
from typing import Any, Literal, Optional, TypedDict


class Tier(TypedDict):
    flat_amount_usd: str
    unit_amount_usd: str
    current_amount_usd: str
    up_to: Optional[int]
    current_usage: int
    projected_usage: Optional[int]
    projected_amount_usd: Optional[str]


class CustomerProductAddon(TypedDict):
    name: str
    description: str
    price_description: Optional[str]
    image_url: Optional[str]
    icon_key: str
    docs_url: Optional[str]
    type: str
    tiers: Optional[Tier]
    tiered: bool
    included_with_main_product: (
        bool  # if the addon is included in the main product subscription, not paid for separately
    )
    inclusion_only: (
        # if the addon subscription state is dependent on the main product subscription state.
        # Ie. addon is automatically sub'd when parent is sub'd.
        bool
    )
    subscribed: bool
    unit: Optional[str]
    unit_amount_usd: Optional[Decimal]
    current_amount_usd: Optional[Decimal]
    current_usage: int
    projected_usage: Optional[int]
    projected_amount_usd: Optional[Decimal]
    contact_support: bool
    usage_key: Optional[str]
    usage_limit: Optional[int]


class CustomerProduct(TypedDict):
    name: str
    description: str
    price_description: Optional[str]
    image_url: Optional[str]
    type: str
    free_allocation: int
    tiers: list[Tier]
    tiered: bool
    unit_amount_usd: Optional[Decimal]
    current_amount_usd: Decimal
    current_usage: int
    usage_limit: Optional[int]
    has_exceeded_limit: bool
    percentage_usage: float
    projected_usage: int
    projected_amount: Decimal
    projected_amount_usd: Decimal
    usage_key: str
    addons: list[CustomerProductAddon]


class LicenseInfo(TypedDict):
    type: str


class BillingPeriod(TypedDict):
    current_period_start: str
    current_period_end: str
    interval: str


class UsageSummary(TypedDict):
    limit: Optional[int]
    usage: Optional[int]


class ProductFeature(TypedDict):
    key: str
    name: str
    description: str
    unit: Optional[str]
    limit: Optional[int]
    note: Optional[str]
    is_plan_default: bool


class CustomerInfo(TypedDict):
    customer_id: Optional[str]
    deactivated: bool
    has_active_subscription: bool
    billing_period: BillingPeriod
    available_product_features: list[ProductFeature]
    current_total_amount_usd: Optional[str]
    current_total_amount_usd_after_discount: Optional[str]
    products: Optional[list[CustomerProduct]]
    custom_limits_usd: Optional[dict[str, int]]
    usage_summary: Optional[dict[str, dict[str, Optional[int]]]]
    free_trial_until: Optional[str]
    discount_percent: Optional[int]
    discount_amount_usd: Optional[str]
    customer_trust_scores: dict[str, int]


class BillingStatus(TypedDict):
    license: LicenseInfo
    customer: CustomerInfo


class ProductPlan(TypedDict):
    """
    A plan for a product that a customer can upgrade/downgrade to.
    """

    product_key: str
    plan_key: str
    name: str
    description: str
    image_url: str
    docs_url: str
    note: Optional[str]
    unit: Optional[str]
    flat_rate: bool
    tiers: Optional[Tier]
    free_allocation: Optional[int]
    features: list[ProductFeature]
    included_if: Optional[str]
    contact_support: Optional[bool]
    unit_amount_usd: Optional[Decimal]


class ProductBaseFeature(TypedDict):
    key: str
    name: str
    description: str
    images: Optional[dict[Literal["light", "dark"], str]]
    icon_key: Optional[str]
    type: Optional[Literal["primary", "secondary"]]


class Product(TypedDict, total=False):
    name: str
    description: str
    usage_key: Optional[str]
    icon_key: str
    image_url: str
    docs_url: str
    plans: list[ProductPlan]
    type: str
    unit: Optional[str]
    addons: Optional[list[Any]]
    contact_support: bool
    inclusion_only: bool
    features: Optional[list[ProductBaseFeature]]
    headline: Optional[str]
