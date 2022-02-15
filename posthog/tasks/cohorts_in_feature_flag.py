from typing import List

from django.core.cache import cache
from django.db.models import TextField
from django.db.models.functions import Cast

from posthog.models.feature_flag import FeatureFlag

key = "cohort_ids_in_feature_flag"


def calculate_cohort_ids_in_feature_flags() -> List[int]:
    flag: FeatureFlag
    cohort_ids = []
    for flag in FeatureFlag.objects.annotate(filters_as_text=Cast("filters", TextField())).filter(
        deleted=False, filters_as_text__contains="cohort"
    ):
        cohort_ids.extend(flag.cohort_ids)

    # dedup
    cohort_ids = list(set(cohort_ids))

    cache.set(key, cohort_ids, None)  # don't expire
    return cohort_ids


def get_cohort_ids_in_feature_flags() -> List[int]:
    try:
        ids = cache.get(key, None)
        if ids:
            return ids
        else:
            return calculate_cohort_ids_in_feature_flags()
    except:
        return calculate_cohort_ids_in_feature_flags()
