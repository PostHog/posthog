import structlog

from posthog.schema import (
    MaxAddonInfo,
    MaxBillingContext,
    MaxBillingContextBillingPeriod,
    MaxBillingContextBillingPeriodInterval,
    MaxBillingContextSettings,
    MaxBillingContextSubscriptionLevel,
    MaxBillingContextTrial,
    MaxProductInfo,
)

from posthog.cloud_utils import get_cached_instance_license
from posthog.models.hog_functions.hog_function import HogFunction
from posthog.models.team.team import Team

from ee.billing.billing_manager import BillingManager

logger = structlog.get_logger(__name__)


def _convert_addon(addon: dict) -> MaxAddonInfo:
    current_usage = addon.get("current_usage") or 0
    percentage_usage = addon.get("percentage_usage") or 0
    return MaxAddonInfo(
        type=addon.get("type", ""),
        name=addon.get("name", ""),
        description=addon.get("description", ""),
        is_used=current_usage > 0,
        has_exceeded_limit=percentage_usage > 1,
        current_usage=current_usage,
        usage_limit=addon.get("usage_limit"),
        percentage_usage=percentage_usage,
        docs_url=addon.get("docs_url"),
        projected_amount_usd=addon.get("projected_amount_usd"),
        projected_amount_usd_with_limit=addon.get("projected_amount_usd_with_limit"),
    )


def _convert_product(product: dict, custom_limits: dict | None, next_period_limits: dict | None) -> MaxProductInfo:
    current_usage = product.get("current_usage") or 0
    percentage_usage = product.get("percentage_usage") or 0
    product_type = product.get("type", "")
    usage_key = product.get("usage_key", "")

    custom_limit = None
    if custom_limits:
        custom_limit = custom_limits.get(product_type) or custom_limits.get(usage_key)

    next_period_limit = None
    if next_period_limits:
        next_period_limit = next_period_limits.get(product_type) or next_period_limits.get(usage_key)

    addons = [_convert_addon(addon) for addon in product.get("addons", [])]

    return MaxProductInfo(
        type=product_type,
        name=product.get("name", ""),
        description=product.get("description", ""),
        is_used=current_usage > 0,
        has_exceeded_limit=percentage_usage > 1,
        current_usage=current_usage,
        usage_limit=product.get("usage_limit"),
        percentage_usage=percentage_usage,
        custom_limit_usd=custom_limit,
        next_period_custom_limit_usd=next_period_limit,
        projected_amount_usd=product.get("projected_amount_usd"),
        projected_amount_usd_with_limit=product.get("projected_amount_usd_with_limit"),
        docs_url=product.get("docs_url"),
        addons=addons,
    )


def _convert_trial(trial: dict | None) -> MaxBillingContextTrial | None:
    if not trial:
        return None
    return MaxBillingContextTrial(
        is_active=trial.get("status") == "active",
        expires_at=trial.get("expires_at"),
        target=trial.get("target"),
    )


def _convert_billing_period(billing_period: dict | None) -> MaxBillingContextBillingPeriod | None:
    if not billing_period:
        return None
    interval_str = billing_period.get("interval", "month")
    interval = (
        MaxBillingContextBillingPeriodInterval.YEAR
        if interval_str == "year"
        else MaxBillingContextBillingPeriodInterval.MONTH
    )
    return MaxBillingContextBillingPeriod(
        current_period_start=billing_period.get("current_period_start", ""),
        current_period_end=billing_period.get("current_period_end", ""),
        interval=interval,
    )


def _get_settings(team: Team) -> MaxBillingContextSettings:
    active_destinations = HogFunction.objects.filter(team=team, enabled=True, type="destination").count()
    return MaxBillingContextSettings(
        autocapture_on=not (team.autocapture_opt_out or False),
        active_destinations=active_destinations,
    )


def billing_response_to_max_context(billing_data: dict, team: Team) -> MaxBillingContext:
    """Convert a BillingManager.get_billing() response dict into a MaxBillingContext model."""
    subscription_level_str = billing_data.get("subscription_level", "free")
    try:
        subscription_level = MaxBillingContextSubscriptionLevel(subscription_level_str)
    except ValueError:
        subscription_level = MaxBillingContextSubscriptionLevel.FREE

    custom_limits = billing_data.get("custom_limits_usd")
    next_period_limits = billing_data.get("next_period_custom_limits_usd")

    products = [_convert_product(p, custom_limits, next_period_limits) for p in billing_data.get("products", [])]

    license_data = billing_data.get("license")
    billing_plan = license_data.get("plan") if isinstance(license_data, dict) else None

    return MaxBillingContext(
        has_active_subscription=billing_data.get("has_active_subscription", False),
        subscription_level=subscription_level,
        billing_plan=billing_plan,
        is_deactivated=billing_data.get("deactivated"),
        products=products,
        billing_period=_convert_billing_period(billing_data.get("billing_period")),
        total_current_amount_usd=billing_data.get("current_total_amount_usd"),
        projected_total_amount_usd=billing_data.get("projected_total_amount_usd"),
        projected_total_amount_usd_after_discount=billing_data.get("projected_total_amount_usd_after_discount"),
        projected_total_amount_usd_with_limit=billing_data.get("projected_total_amount_usd_with_limit"),
        projected_total_amount_usd_with_limit_after_discount=billing_data.get(
            "projected_total_amount_usd_with_limit_after_discount"
        ),
        startup_program_label=billing_data.get("startup_program_label"),
        startup_program_label_previous=billing_data.get("startup_program_label_previous"),
        trial=_convert_trial(billing_data.get("trial")),
        settings=_get_settings(team),
        usage_history=None,
        spend_history=None,
    )


def fetch_server_billing_context(team: Team) -> MaxBillingContext | None:
    """Fetch billing data from the billing service and convert to MaxBillingContext.

    Returns None if the billing service is unreachable or the organization has no billing set up.
    """
    try:
        license = get_cached_instance_license()
        if not license or not license.is_v2_license:
            return None

        billing_manager = BillingManager(license)
        billing_data = billing_manager.get_billing(team.organization)
        return billing_response_to_max_context(billing_data, team)
    except Exception:
        logger.exception("Failed to fetch server-side billing context")
        return None
