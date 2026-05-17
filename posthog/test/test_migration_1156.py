from typing import Any

from posthog.test.base import NonAtomicTestMigrations


class NormalizeCohortFlagOperatorsMigrationTest(NonAtomicTestMigrations):
    migrate_from = "1155_sharingconfiguration_interviewee_context"
    migrate_to = "1156_normalize_cohort_flag_operators"

    CLASS_DATA_LEVEL_SETUP = False

    def setUpBeforeMigration(self, apps: Any) -> None:
        Organization = apps.get_model("posthog", "Organization")
        Project = apps.get_model("posthog", "Project")
        Team = apps.get_model("posthog", "Team")
        FeatureFlag = apps.get_model("posthog", "FeatureFlag")

        organization = Organization.objects.create(name="o1")
        project = Project.objects.create(organization=organization, name="p1", id=1000001)
        team = Team.objects.create(organization=organization, name="t1", project=project)

        def make_flag(key: str, properties: list[dict]) -> Any:
            return FeatureFlag.objects.create(
                team=team,
                key=key,
                filters={"groups": [{"rollout_percentage": 100, "properties": properties}]},
            )

        # Invalid cohort operators that must be normalized.
        self.is_not_flag = make_flag(
            "legacy-is-not", [{"key": "id", "type": "cohort", "value": 1, "operator": "is_not"}]
        )
        self.exact_flag = make_flag("legacy-exact", [{"key": "id", "type": "cohort", "value": 1, "operator": "exact"}])

        # Valid cohort states that must be left untouched.
        self.in_flag = make_flag("valid-in", [{"key": "id", "type": "cohort", "value": 1, "operator": "in"}])
        self.not_in_flag = make_flag(
            "valid-not-in", [{"key": "id", "type": "cohort", "value": 1, "operator": "not_in"}]
        )
        self.no_operator_flag = make_flag("cohort-no-operator", [{"key": "id", "type": "cohort", "value": 1}])

        # Non-cohort property with is_not must be left untouched.
        self.person_flag = make_flag(
            "person-is-not", [{"key": "email", "type": "person", "value": "x@y.com", "operator": "is_not"}]
        )

        # Mixed group: only the cohort property is normalized, the sibling person property is not.
        self.mixed_flag = make_flag(
            "mixed-group",
            [
                {"key": "id", "type": "cohort", "value": 1, "operator": "is_not"},
                {"key": "email", "type": "person", "value": "x@y.com", "operator": "is_not"},
            ],
        )

    def test_migration(self) -> None:
        for flag in (
            self.is_not_flag,
            self.exact_flag,
            self.in_flag,
            self.not_in_flag,
            self.no_operator_flag,
            self.person_flag,
            self.mixed_flag,
        ):
            flag.refresh_from_db()

        assert self.is_not_flag.filters["groups"][0]["properties"][0]["operator"] == "not_in"
        assert self.exact_flag.filters["groups"][0]["properties"][0]["operator"] == "in"

        assert self.in_flag.filters["groups"][0]["properties"][0]["operator"] == "in"
        assert self.not_in_flag.filters["groups"][0]["properties"][0]["operator"] == "not_in"
        assert "operator" not in self.no_operator_flag.filters["groups"][0]["properties"][0]

        assert self.person_flag.filters["groups"][0]["properties"][0]["operator"] == "is_not"

        mixed_props = self.mixed_flag.filters["groups"][0]["properties"]
        assert mixed_props[0]["operator"] == "not_in"
        assert mixed_props[1]["operator"] == "is_not"
