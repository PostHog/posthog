# Test cases for feature-flags-no-raw-filters-access.
# ruff: noqa


class FeatureFlag:
    filters: dict = {}
    variants: list = []

    def get_filters(self) -> dict:
        return self.filters


feature_flag = FeatureFlag()
flag = FeatureFlag()
existing_targeting_flag = FeatureFlag()
ff_record = FeatureFlag()
some_ff = FeatureFlag()
dashboard = object()
row = FeatureFlag()
serializer = object()


class FlagContainer:
    ff = FeatureFlag()


instance = FlagContainer()

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
# ruleid: feature-flags-no-raw-filters-access
ff_record.filters.get("groups")
# ruleid: feature-flags-no-raw-filters-access
some_ff.filters["groups"]
# ruleid: feature-flags-no-raw-filters-access
instance.ff.filters["groups"]
# ruleid: feature-flags-no-raw-filters-access
flag.filters |= {"groups": []}
# ruleid: feature-flags-no-raw-filters-access
payloads = (flag.filters or {}).get("payloads")
# ruleid: feature-flags-no-raw-filters-access
groups = (feature_flag.filters or {})["groups"]
# ruleid: feature-flags-no-raw-filters-access
groups = feature_flag.get_filters()["groups"]
# ruleid: feature-flags-no-raw-filters-access
multivariate = instance.ff.get_filters().get("multivariate")
# ruleid: feature-flags-no-raw-filters-access
holdout = row.get_filters().get("holdout")

# Public model accessors are fine
# ok: feature-flags-no-raw-filters-access
variants = feature_flag.variants
# Unrelated .filters attributes on non-flag objects are fine
# ok: feature-flags-no-raw-filters-access
date_from = dashboard.filters["date_from"]
# ok: feature-flags-no-raw-filters-access
properties = (dashboard.filters or {}).get("properties")
# Passing the blob around without digging in is not flagged
# ok: feature-flags-no-raw-filters-access
blob = feature_flag.filters
# ok: feature-flags-no-raw-filters-access
blob = feature_flag.get_filters()
# ok: feature-flags-no-raw-filters-access
blob = feature_flag.filters or {}
# ok: feature-flags-no-raw-filters-access
date_from = serializer.get_filters(dashboard)["date_from"]
