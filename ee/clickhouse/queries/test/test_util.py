from posthog.clickhouse.client import sync_execute
from posthog.queries.breakdown_props import _parse_breakdown_cohorts

from products.actions.backend.models.action import Action
from products.cohorts.backend.models.cohort import Cohort


def test_parse_breakdown_cohort_query(db, team):
    action = Action.objects.create(team=team, name="$pageview", steps_json=[{"event": "$pageview"}])
    cohort1 = Cohort.objects.create(team=team, groups=[{"action_id": action.pk, "days": 3}], name="cohort1")
    queries, params = _parse_breakdown_cohorts([cohort1])
    assert len(queries) == 1
    sync_execute(queries[0], params)
