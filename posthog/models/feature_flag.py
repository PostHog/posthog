import hashlib
from typing import Any, Dict, List

from django.contrib.postgres.fields import JSONField
from django.db import models
from django.db.models.expressions import ExpressionWrapper, RawSQL
from django.db.models.fields import BooleanField
from django.db.models.query import QuerySet
from django.utils import timezone
from sentry_sdk.api import capture_exception

from posthog.models.filters.mixins.utils import cached_property
from posthog.models.team import Team
from posthog.queries.base import properties_to_Q

from .filters import Filter
from .person import Person

__LONG_SCALE__ = float(0xFFFFFFFFFFFFFFF)


class FeatureFlag(models.Model):
    class Meta:
        constraints = [models.UniqueConstraint(fields=["team", "key"], name="unique key for team")]

    key: models.CharField = models.CharField(max_length=400)
    name: models.TextField = models.TextField(
        blank=True,
    )  # contains description for the FF (field name `name` is kept for backwards-compatibility)

    filters: JSONField = JSONField(default=dict)
    rollout_percentage: models.IntegerField = models.IntegerField(null=True, blank=True)

    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    created_by: models.ForeignKey = models.ForeignKey("User", on_delete=models.CASCADE)
    created_at: models.DateTimeField = models.DateTimeField(default=timezone.now)
    deleted: models.BooleanField = models.BooleanField(default=False)
    active: models.BooleanField = models.BooleanField(default=True)

    def distinct_id_matches(self, distinct_id: str) -> bool:
        return FeatureFlagMatcher(distinct_id, self).is_match()

    def get_analytics_metadata(self) -> Dict:
        filter_count = sum(len(group.get("properties", [])) for group in self.groups)

        return {
            "groups_count": len(self.groups),
            "has_filters": filter_count > 0,
            "has_rollout_percentage": any(group.get("rollout_percentage") for group in self.groups),
            "filter_count": filter_count,
            "created_at": self.created_at,
        }

    @property
    def groups(self):
        return self.get_filters().get("groups", [])

    def get_filters(self):
        if "groups" in self.filters:
            return self.filters
        else:
            # :TRICKY: Keep this backwards compatible.
            #   We don't want to migrate to avoid /decide endpoint downtime until this code has been deployed
            return {
                "groups": [
                    {"properties": self.filters.get("properties", []), "rollout_percentage": self.rollout_percentage}
                ]
            }


class FeatureFlagMatcher:
    def __init__(self, distinct_id: str, feature_flag: FeatureFlag):
        self.distinct_id = distinct_id
        self.feature_flag = feature_flag

    def is_match(self):
        return any(self.is_group_match(group, index) for index, group in enumerate(self.feature_flag.groups))

    def is_group_match(self, group: Dict, group_index: int):
        rollout_percentage = group.get("rollout_percentage")
        if len(group.get("properties", [])) > 0:
            if not self._match_distinct_id(group_index):
                return False
            elif not rollout_percentage:
                return True

        if rollout_percentage is not None and self._hash > (rollout_percentage / 100):
            return False

        return True

    def _match_distinct_id(self, group_index: int) -> bool:
        return len(self.query_groups) > 0 and self.query_groups[0][group_index]

    @cached_property
    def query_groups(self) -> List[List[bool]]:
        query: QuerySet = Person.objects.filter(
            team_id=self.feature_flag.team_id,
            persondistinctid__distinct_id=self.distinct_id,
            persondistinctid__team_id=self.feature_flag.team_id,
        )

        fields = []
        for index, group in enumerate(self.feature_flag.groups):
            key = f"group_{index}"

            if len(group.get("properties", {})) > 0:
                expr: Any = properties_to_Q(
                    Filter(data=group).properties, team_id=self.feature_flag.team_id, is_person_query=True
                )
            else:
                expr = RawSQL("true", [])

            query = query.annotate(**{key: ExpressionWrapper(expr, output_field=BooleanField())})
            fields.append(key)

        return list(query.values_list(*fields))

    # This function takes a distinct_id and a feature flag key and returns a float between 0 and 1.
    # Given the same distinct_id and key, it'll always return the same float. These floats are
    # uniformly distributed between 0 and 1, so if we want to show this feature to 20% of traffic
    # we can do _hash(key, distinct_id) < 0.2
    @cached_property
    def _hash(self) -> float:
        hash_key = "%s.%s" % (self.feature_flag.key, self.distinct_id)
        hash_val = int(hashlib.sha1(hash_key.encode("utf-8")).hexdigest()[:15], 16)
        return hash_val / __LONG_SCALE__


def get_active_feature_flags(team: Team, distinct_id: str) -> List[str]:
    flags_enabled = []
    feature_flags = FeatureFlag.objects.filter(team=team, active=True, deleted=False).only(
        "id", "team_id", "filters", "key", "rollout_percentage",
    )
    for feature_flag in feature_flags:
        try:
            # distinct_id will always be a string, but data can have non-string values ("Any")
            if feature_flag.distinct_id_matches(distinct_id):
                flags_enabled.append(feature_flag.key)
        except Exception as err:
            capture_exception(err)
    return flags_enabled
