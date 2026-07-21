from posthog.models.organization import ProductFeature

VALID_RETENTION_PERIODS = ["30d", "90d", "1y", "5y"]

# Ascending day-length of each valid period, used to resolve an entitlement down to
# the longest period it fully covers.
RETENTION_PERIOD_DAYS = {"30d": 30, "90d": 90, "1y": 365, "5y": 1825}


def parse_feature_to_entitlement(retention_feature: ProductFeature | None) -> str | None:
    if retention_feature is None:
        return None

    retention_limit: int | None = retention_feature.get("limit")
    retention_unit: str | None = retention_feature.get("unit")

    if retention_limit is None or retention_unit is None:
        return None

    match retention_unit.lower():
        case "day" | "days":
            entitlement_days = retention_limit
        case "month" | "months":
            entitlement_days = round(retention_limit * 365 / 12)
        case "year" | "years":
            entitlement_days = retention_limit * 365
        case _:
            return None

    # Entitlements don't always land on a canonical period (e.g. a 6-month or 3-year plan).
    # Resolve down to the longest valid period the entitlement fully covers rather than
    # rejecting anything that isn't an exact match.
    eligible = [period for period in VALID_RETENTION_PERIODS if RETENTION_PERIOD_DAYS[period] <= entitlement_days]
    return eligible[-1] if eligible else VALID_RETENTION_PERIODS[0]


def validate_retention_period(retention_period: str | None) -> bool:
    return retention_period is not None and retention_period in VALID_RETENTION_PERIODS


def retention_violates_entitlement(current_retention: str, highest_retention_entitlement: str) -> bool:
    return VALID_RETENTION_PERIODS.index(current_retention) > VALID_RETENTION_PERIODS.index(
        highest_retention_entitlement
    )
