from posthog.models.organization import ProductFeature

VALID_RETENTION_PERIODS = ["30d", "90d", "1y", "5y"]


def parse_feature_to_entitlement(retention_feature: ProductFeature | None) -> str | None:
    if retention_feature is None:
        return None

    retention_limit: int | None = retention_feature.get("limit")
    retention_unit: str | None = retention_feature.get("unit")

    if retention_limit is None or retention_unit is None:
        return None

    match retention_unit.lower():
        case "day" | "days":
            highest_retention_entitlement = f"{retention_limit}d"
        case "month" | "months":
            if retention_limit < 12:
                highest_retention_entitlement = f"{retention_limit * 30}d"
            else:
                highest_retention_entitlement = f"{retention_limit // 12}y"
        case "year" | "years":
            highest_retention_entitlement = f"{retention_limit}y"
        case _:
            return None

    if not validate_retention_period(highest_retention_entitlement):
        return None

    return highest_retention_entitlement


def validate_retention_period(retention_period: str | None) -> bool:
    return retention_period is not None and retention_period in VALID_RETENTION_PERIODS


def retention_violates_entitlement(current_retention: str, highest_retention_entitlement: str) -> bool:
    return VALID_RETENTION_PERIODS.index(current_retention) > VALID_RETENTION_PERIODS.index(
        highest_retention_entitlement
    )
