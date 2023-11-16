from posthog.test.base import (
    APIBaseTest,
)
from posthog.models.cohort import Cohort
from posthog.models.cohort.util import get_sorted_cohort_ids


class TestFeatureFlagUtils(APIBaseTest):
    def setUp(self):
        super().setUp()

    def test_get_destination_creation_order(self):
        cohorts = {}

        def create_cohort(name):
            cohorts[name] = Cohort.objects.create(
                team=self.team,
                name=name,
                filters={
                    "properties": {
                        "type": "AND",
                        "values": [
                            {"key": "name", "value": "test", "type": "person"},
                        ],
                    }
                },
            )

        create_cohort("a")
        create_cohort("b")
        create_cohort("c")

        # (c)-->(b)
        cohorts["c"].filters["properties"]["values"][0] = {
            "key": "id",
            "value": cohorts["b"].pk,
            "type": "cohort",
            "negation": True,
        }
        cohorts["c"].save()

        # (a)-->(c)
        cohorts["a"].filters["properties"]["values"][0] = {
            "key": "id",
            "value": cohorts["c"].pk,
            "type": "cohort",
            "negation": True,
        }
        cohorts["a"].save()

        cohort_ids = {cohorts["a"].pk, cohorts["b"].pk, cohorts["c"].pk}
        seen_cohorts_cache = {
            cohorts["a"].pk: cohorts["a"],
            cohorts["b"].pk: cohorts["b"],
            cohorts["c"].pk: cohorts["c"],
        }

        # (a)-->(c)-->(b)
        # create b first, since it doesn't depend on any other cohorts
        # then c, because it depends on b
        # then a, because it depends on c

        # thus destination creation order: b, c, a
        destination_creation_order = [cohorts["b"].pk, cohorts["c"].pk, cohorts["a"].pk]
        sorted_cohort_ids = get_sorted_cohort_ids(cohort_ids, seen_cohorts_cache)
        self.assertEqual(sorted_cohort_ids, destination_creation_order)
