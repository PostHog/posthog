from django.db import models
from django.contrib.postgres.fields import JSONField
from django.utils import timezone
from .person import Person
from .filter import Filter
import hashlib

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
            if (
                not Person.objects.filter(team_id=self.team_id, persondistinctid__distinct_id=distinct_id)
                .filter(Filter(data=self.filters).properties_to_Q(team_id=self.team_id, is_person_query=True))
                .exists()
            ):
                return False
            elif not self.rollout_percentage:
                return True

        if self.rollout_percentage:
            hash = self._hash(self.key, distinct_id)
            if hash <= (self.rollout_percentage / 100):
                return True
        return False

    # This function takes a distinct_id and a feature flag key and returns a float between 0 and 1.
    # Given the same distinct_id and key, it'll always return the same float. These floats are
    # uniformly distributed between 0 and 1, so if we want to show this feature to 20% of traffic
    # we can do _hash(key, distinct_id) < 0.2
    def _hash(self, key: str, distinct_id: str) -> float:
        hash_key = "%s.%s" % (key, distinct_id)
        hash_val = int(hashlib.sha1(hash_key.encode("utf-8")).hexdigest()[:15], 16)
        return hash_val / __LONG_SCALE__
