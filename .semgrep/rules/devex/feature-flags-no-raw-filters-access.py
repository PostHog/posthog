# Test cases for feature-flags-no-raw-filters-access.
# ruff: noqa


class FeatureFlag:
    filters: dict = {}
    variants: list = []


feature_flag = FeatureFlag()
flag = FeatureFlag()
existing_targeting_flag = FeatureFlag()
dashboard = object()

# ruleid: feature-flags-no-raw-filters-access
groups = feature_flag.filters["groups"]
# ruleid: feature-flags-no-raw-filters-access
multivariate = flag.filters.get("multivariate", {})
# ruleid: feature-flags-no-raw-filters-access
variants = feature_flag.filters["multivariate"]["variants"]
# ruleid: feature-flags-no-raw-filters-access
aggregation = existing_targeting_flag.filters.get("aggregation_group_type_index")
# ruleid: feature-flags-no-raw-filters-access
feature_flag.filters = {"groups": []}
# ruleid: feature-flags-no-raw-filters-access
flag.filters["groups"][0]["rollout_percentage"] = 100
# ruleid: feature-flags-no-raw-filters-access
flag.filters.update({"payloads": {}})

# Public model accessors are fine
# ok: feature-flags-no-raw-filters-access
variants = feature_flag.variants
# Unrelated .filters attributes on non-flag objects are fine
# ok: feature-flags-no-raw-filters-access
date_from = dashboard.filters["date_from"]
# Passing the blob around without digging in is not flagged
# ok: feature-flags-no-raw-filters-access
blob = feature_flag.filters
