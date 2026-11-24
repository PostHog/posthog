from posthog.models.organization import OrganizationUsageInfo

from ee.billing.quota_limiting import (
    BILLING_STATUS_STAMP_KEYS,
    INFORMATIONAL_USAGE_RESOURCES,
    QuotaResource,
    UsageCounters,
)


def test_usage_keys_stay_in_sync() -> None:
    org_usage_keys = set(OrganizationUsageInfo.__annotations__.keys()) - {"period", *BILLING_STATUS_STAMP_KEYS}

    quota_resource_keys = {resource.value for resource in QuotaResource}
    usage_counter_keys = set(UsageCounters.__annotations__.keys())

    informational_keys = set(INFORMATIONAL_USAGE_RESOURCES)
    assert informational_keys <= org_usage_keys
    assert not informational_keys & quota_resource_keys, "informational resources must not be QuotaResources"
    missing_from_quota = org_usage_keys - quota_resource_keys - informational_keys
    extra_in_quota = quota_resource_keys - org_usage_keys
    assert not missing_from_quota, f"QuotaResource is missing keys from OrganizationUsageInfo: {missing_from_quota}"
    assert not extra_in_quota, f"QuotaResource has extra keys not in OrganizationUsageInfo: {extra_in_quota}"

    missing_from_counters = org_usage_keys - usage_counter_keys
    extra_in_counters = usage_counter_keys - org_usage_keys
    assert not missing_from_counters, (
        f"UsageCounters is missing keys from OrganizationUsageInfo: {missing_from_counters}"
    )
    assert not extra_in_counters, f"UsageCounters has extra keys not in OrganizationUsageInfo: {extra_in_counters}"
