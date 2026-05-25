"""Create the `web-analytics-precompute` feature flag and enable it for team 2 only.

The flag lives on the team that owns `posthoganalytics.api_key` (the first team
by ID in the local instance). It's evaluated via `posthoganalytics.feature_enabled`
from `web_overview_lazy_precompute.py`, which passes the *target* team's UUID as
distinct_id. So matching on that distinct_id is the cleanest local-dev gate.
"""
import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
import django

django.setup()

from posthog.models import FeatureFlag, Team, User

FLAG_KEY = "web-analytics-precompute"
TARGET_TEAM_ID = 2

target = Team.objects.get(pk=TARGET_TEAM_ID)
owner_team = Team.objects.order_by("id").first()  # the team posthoganalytics.api_key points to
assert owner_team is not None

creator = (
    User.objects.filter(is_staff=True, organization_membership__organization=owner_team.organization).first()
    or User.objects.filter(is_staff=True).first()
)

# Match on distinct_id = target team's UUID. The runner calls
# `feature_enabled("web-analytics-precompute", str(team.uuid), groups={...})`,
# so this filter fires only for team 2.
filters = {
    "groups": [
        {
            "properties": [
                {
                    "key": "$distinct_id",
                    "type": "person",
                    "value": [str(target.uuid)],
                    "operator": "exact",
                }
            ],
            "rollout_percentage": 100,
        }
    ],
    "payloads": {},
    "multivariate": None,
}

flag, created = FeatureFlag.objects.update_or_create(
    key=FLAG_KEY,
    team=owner_team,
    defaults={
        "name": "Web analytics: route web_overview_query through precompute path",
        "filters": filters,
        "active": True,
        "deleted": False,
        "created_by": creator,
    },
)

action = "created" if created else "updated"
print(f"{action} feature flag pk={flag.pk} key={flag.key!r} owner_team={owner_team.pk} active={flag.active}")
print(f"target team (id={target.pk}, uuid={target.uuid}, name={target.name!r})")
print(f"filters = {flag.filters}")
