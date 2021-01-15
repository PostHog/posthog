import hashlib
from typing import Dict, List

import posthoganalytics
from django.contrib.postgres.fields import JSONField
from django.db import models
from django.dispatch import receiver
from django.utils import timezone

from posthog.models.team import Team
from posthog.queries.base import properties_to_Q

from .filters import Filter
from .person import Person

__LONG_SCALE__ = float(0xFFFFFFFFFFFFFFF)


class FeatureFlag(models.Model):
    class Meta:
        constraints = [models.UniqueConstraint(fields=["team", "key"], name="unique key for team")]

    name: models.CharField = models.CharField(max_length=400)
    key: models.CharField = models.CharField(max_length=400)

    filters: JSONField = JSONField(default=dict)
    rollout_percentage: models.IntegerField = models.IntegerField(null=True, blank=True)

    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    created_by: models.ForeignKey = models.ForeignKey("User", on_delete=models.CASCADE)
    created_at: models.DateTimeField = models.DateTimeField(default=timezone.now)
    deleted: models.BooleanField = models.BooleanField(default=False)
    active: models.BooleanField = models.BooleanField(default=True)

    def distinct_id_matches(self, distinct_id: str) -> bool:
        if len(self.filters.get("properties", [])) > 0:
            if not self._match_distinct_id(distinct_id):
                return False
            elif not self.rollout_percentage:
                return True

        if self.rollout_percentage:
            hash = self._hash(self.key, distinct_id)
            if hash <= (self.rollout_percentage / 100):
                return True
        return False

    def _match_distinct_id(self, distinct_id: str) -> bool:
        filter = Filter(data=self.filters)
        return (
            Person.objects.filter(team_id=self.team_id, persondistinctid__distinct_id=distinct_id)
            .filter(properties_to_Q(filter.properties, team_id=self.team_id, is_person_query=True))
            .exists()
        )

    # This function takes a distinct_id and a feature flag key and returns a float between 0 and 1.
    # Given the same distinct_id and key, it'll always return the same float. These floats are
    # uniformly distributed between 0 and 1, so if we want to show this feature to 20% of traffic
    # we can do _hash(key, distinct_id) < 0.2
    def _hash(self, key: str, distinct_id: str) -> float:
        hash_key = "%s.%s" % (key, distinct_id)
        hash_val = int(hashlib.sha1(hash_key.encode("utf-8")).hexdigest()[:15], 16)
        return hash_val / __LONG_SCALE__

    def get_analytics_metadata(self) -> Dict:
        filter_count: int = len(self.filters.get("properties", []),) if self.filters else 0

        return {
            "rollout_percentage": self.rollout_percentage,
            "has_filters": True if self.filters and self.filters.get("properties") else False,
            "filter_count": filter_count,
            "created_at": self.created_at,
        }


@receiver(models.signals.post_save, sender=FeatureFlag)
def feature_flag_created(sender, instance, created, raw, using, **kwargs):

    if instance.created_by:
        event_name: str = "feature flag created" if created else "feature flag updated"
        posthoganalytics.capture(
            instance.created_by.distinct_id, event_name, instance.get_analytics_metadata(),
        )


def get_active_feature_flags(team: Team, distinct_id: str) -> List[str]:
    flags_enabled = []
    feature_flags = FeatureFlag.objects.filter(team=team, active=True, deleted=False).only(
        "id", "team_id", "filters", "key", "rollout_percentage"
    )
    for feature_flag in feature_flags:
        # distinct_id will always be a string, but data can have non-string values ("Any")
        if feature_flag.distinct_id_matches(distinct_id):
            flags_enabled.append(feature_flag.key)
    return flags_enabled
