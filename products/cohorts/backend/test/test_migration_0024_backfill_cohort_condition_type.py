from typing import Any

from posthog.test.base import TestMigrations

BEHAVIORAL_FILTERS = {
    "properties": {
        "type": "OR",
        "values": [
            {
                "type": "AND",
                "values": [
                    {"key": "$pageview", "type": "behavioral", "value": "performed_event", "event_type": "events"},
                    {"key": "email", "type": "person", "value": "x", "operator": "icontains"},
                ],
            }
        ],
    }
}
BEHAVIORAL_CONDITION_TYPE = {"person_properties": True, "behavioral": True, "lifecycle": False, "cohorts": False}
STALE_CONDITION_TYPE = {"person_properties": True, "behavioral": False, "lifecycle": False, "cohorts": False}


class TestBackfillCohortConditionType(TestMigrations):
    app = "cohorts"
    migrate_from = "0021_cohort_backfill_refusal"
    migrate_to = "0024_backfill_cohort_condition_type"

    def setUpBeforeMigration(self, apps: Any) -> None:
        Cohort = apps.get_model("cohorts", "Cohort")

        def create(**fields: Any) -> int:
            return Cohort.objects.create(team_id=self.team.id, cohort_type="realtime", **fields).id

        self.unclassified = create(filters=BEHAVIORAL_FILTERS)
        self.unclassified_deleted = create(filters=BEHAVIORAL_FILTERS, deleted=True)
        self.already_classified = create(filters=BEHAVIORAL_FILTERS, condition_type=STALE_CONDITION_TYPE)
        self.without_leaves = create(filters={"properties": {"type": "OR", "values": []}})
        self.without_filters = create(filters=None)
        self.unreadable = create(
            filters={"properties": {"type": "AND", "values": [{"type": "behavioral", "value": ["performed_event"]}]}}
        )

    def test_classifies_only_the_cohorts_left_unclassified(self) -> None:
        Cohort = self.apps.get_model("cohorts", "Cohort")  # type: ignore[union-attr]
        condition_types = dict(Cohort.objects.filter(team_id=self.team.id).values_list("id", "condition_type"))

        assert condition_types == {
            self.unclassified: BEHAVIORAL_CONDITION_TYPE,
            self.unclassified_deleted: BEHAVIORAL_CONDITION_TYPE,
            self.already_classified: STALE_CONDITION_TYPE,
            self.without_leaves: None,
            self.without_filters: None,
            self.unreadable: None,
        }
