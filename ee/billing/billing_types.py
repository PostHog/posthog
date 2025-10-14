from decimal import Decimal
from typing import Any, Literal, TypedDict


class Tier(TypedDict):
    flat_amount_usd: str
    unit_amount_usd: str
    current_amount_usd: str
    up_to: int | None
    current_usage: int
    projected_usage: int | None
    projected_amount_usd: str | None


class CustomerProductAddon(TypedDict):
    name: str
    description: str
    price_description: str | None
    image_url: str | None
    icon_key: str
    docs_url: str | None
    type: str
    tiers: Tier | None
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
    unit: str | None
    unit_amount_usd: Decimal | None
    current_amount_usd: Decimal | None
    current_usage: int
    projected_usage: int | None
    projected_amount_usd: Decimal | None
    contact_support: bool
    usage_key: str | None
    usage_limit: int | None


class CustomerProduct(TypedDict):
    name: str
    description: str
    price_description: str | None
    image_url: str | None
    type: str
    free_allocation: int
    tiers: list[Tier]
    tiered: bool
    unit_amount_usd: Decimal | None
    current_amount_usd: Decimal
    current_usage: int
    usage_limit: int | None
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
    limit: int | None
    usage: int | None


class ProductFeature(TypedDict):
    key: str
    name: str
    description: str
    unit: str | None
    limit: int | None
    note: str | None
    is_plan_default: bool


class CustomerInfo(TypedDict):
    customer_id: str | None
    deactivated: bool
    has_active_subscription: bool
    billing_period: BillingPeriod
    available_product_features: list[ProductFeature]
    current_total_amount_usd: str | None
    current_total_amount_usd_after_discount: str | None
    products: list[CustomerProduct] | None
    custom_limits_usd: dict[str, int] | None
    usage_summary: dict[str, dict[str, int | None]] | None
    free_trial_until: str | None
    discount_percent: int | None
    discount_amount_usd: str | None
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
    note: str | None
    unit: str | None
    flat_rate: bool
    tiers: Tier | None
    free_allocation: int | None
    features: list[ProductFeature]
    included_if: str | None
    contact_support: bool | None
    unit_amount_usd: Decimal | None


class ProductBaseFeature(TypedDict):
    key: str
    name: str
    description: str
    images: dict[Literal["light", "dark"], str] | None
    icon_key: str | None
    type: Literal["primary", "secondary"] | None


class Product(TypedDict, total=False):
    name: str
    description: str
    usage_key: str | None
    icon_key: str
    image_url: str
    docs_url: str
    plans: list[ProductPlan]
    type: str
    unit: str | None
    addons: list[Any] | None
    contact_support: bool
    inclusion_only: bool
    features: list[ProductBaseFeature] | None
    headline: str | None
