from __future__ import annotations

from typing import Any

from posthog.test.base import BaseTest

from django.core.management import call_command

from posthog.models.cohort.cohort import Cohort
from posthog.models.team.team import Team

from common.hogvm.python.operation import HOGQL_BYTECODE_VERSION


def _has_condition_hash(obj: Any) -> bool:
    if isinstance(obj, dict):
        if "conditionHash" in obj:
            return True
        return any(_has_condition_hash(v) for v in obj.values())
    if isinstance(obj, list):
        return any(_has_condition_hash(v) for v in obj)
    return False


def _make_realtime_filters(email: str = "test@example.com") -> dict[str, Any]:
    return {
        "properties": {
            "type": "AND",
            "values": [
                {"type": "person", "key": "email", "operator": "exact", "value": email},
                {"type": "behavioral", "key": "purchase", "value": "performed_event", "event_type": "events"},
            ],
        }
    }


def _make_unsupported_filters(email: str = "test@example.com") -> dict[str, Any]:
    return {
        "properties": {
            "type": "AND",
            "values": [
                {"type": "person", "key": "email", "operator": "exact", "value": email},
                {
                    "type": "behavioral",
                    "key": "signup",
                    "value": "performed_event_regularly",
                    "event_type": "events",
                },
            ],
        }
    }


def _make_person_only_filters(email: str = "test@example.com") -> dict[str, Any]:
    return {
        "properties": {
            "type": "AND",
            "values": [
                {"type": "person", "key": "email", "operator": "icontains", "value": email},
            ],
        }
    }


class TestResaveCohortsCommandSingleTeam(BaseTest):
    def test_resave_single_team_five_types(self):
        team: Team = self.team

        ref = Cohort.objects.create(team=team, name="ref")

        cohorts = [
            Cohort.objects.create(team=team, name="realtime1", filters=_make_realtime_filters()),
            Cohort.objects.create(team=team, name="unsupported1", filters=_make_unsupported_filters()),
            Cohort.objects.create(team=team, name="person_only1", filters=_make_person_only_filters()),
            Cohort.objects.create(
                team=team,
                name="cohort_filter1",
                filters={
                    "properties": {
                        "type": "AND",
                        "values": [
                            {"type": "cohort", "key": "id", "value": ref.id},
                        ],
                    }
                },
            ),
            Cohort.objects.create(
                team=team,
                name="realtime2",
                filters={
                    "properties": {
                        "type": "AND",
                        "values": [
                            {
                                "type": "behavioral",
                                "key": "page_view",
                                "value": "performed_event",
                                "event_type": "events",
                            },
                        ],
                    }
                },
            ),
        ]

        # Ensure initial state has no cohort_type (and no inline bytecode yet)
        for c in cohorts:
            assert c.cohort_type is None
            assert not _has_condition_hash(c.filters)

        # Run command for this team
        call_command("resave_cohorts", team_id=team.id)

        # Reload and assert
        updated = {c.id: Cohort.objects.get(id=c.id) for c in cohorts}

        # realtime-capable
        assert updated[cohorts[0].id].cohort_type == "realtime"
        assert _has_condition_hash(updated[cohorts[0].id].filters)
        # Assert behavioral('purchase') bytecode
        filters_0 = updated[cohorts[0].id].filters
        assert filters_0 is not None
        assert isinstance(filters_0, dict)
        behavioral_filter_0 = filters_0["properties"]["values"][1]
        assert behavioral_filter_0["type"] == "behavioral"
        assert behavioral_filter_0["bytecode"] == ["_H", HOGQL_BYTECODE_VERSION, 32, "purchase", 32, "event", 1, 1, 11]
        assert behavioral_filter_0["conditionHash"] is not None

        # unsupported stays None (but supported sub-filters may still emit inline bytecode)
        assert updated[cohorts[1].id].cohort_type is None
        assert _has_condition_hash(updated[cohorts[1].id].filters)
        # Unsupported behavioral value should not emit behavioral bytecode
        filters_1 = updated[cohorts[1].id].filters
        assert filters_1 is not None
        assert isinstance(filters_1, dict)
        behavioral_filter_1 = filters_1["properties"]["values"][1]
        assert behavioral_filter_1["type"] == "behavioral"
        assert "bytecode" not in behavioral_filter_1 or behavioral_filter_1.get("bytecode") is None

        # person-only is realtime-capable
        assert updated[cohorts[2].id].cohort_type == "realtime"
        assert _has_condition_hash(updated[cohorts[2].id].filters)
        # Person property should have bytecode
        filters_2 = updated[cohorts[2].id].filters
        assert filters_2 is not None
        assert isinstance(filters_2, dict)
        person_filter_2 = filters_2["properties"]["values"][0]
        assert person_filter_2["type"] == "person"
        assert "bytecode" in person_filter_2
        assert person_filter_2["bytecode"] is not None
        assert person_filter_2["conditionHash"] is not None

        # cohort filter is realtime-capable
        assert updated[cohorts[3].id].cohort_type == "realtime"
        assert _has_condition_hash(updated[cohorts[3].id].filters)

        # simple behavioral realtime
        assert updated[cohorts[4].id].cohort_type == "realtime"
        assert _has_condition_hash(updated[cohorts[4].id].filters)
        # Assert behavioral('page_view') bytecode
        filters_4 = updated[cohorts[4].id].filters
        assert filters_4 is not None
        assert isinstance(filters_4, dict)
        behavioral_filter_4 = filters_4["properties"]["values"][0]
        assert behavioral_filter_4["type"] == "behavioral"
        assert behavioral_filter_4["bytecode"] == ["_H", HOGQL_BYTECODE_VERSION, 32, "page_view", 32, "event", 1, 1, 11]
        assert behavioral_filter_4["conditionHash"] is not None


class TestResaveCohortsCommandWithDependencies(BaseTest):
    def test_cohort_dependency_blocks_realtime(self):
        """Test that a cohort referencing a non-realtime cohort cannot be realtime."""
        team: Team = self.team

        # Create a cohort with unsupported filters (cannot be realtime)
        unsupported_cohort = Cohort.objects.create(
            team=team,
            name="unsupported_dependency",
            filters=_make_unsupported_filters(),  # This cannot be realtime
        )

        # Create a cohort that would be realtime on its own (person-only filter)
        # but references the unsupported cohort
        dependent_cohort = Cohort.objects.create(
            team=team,
            name="dependent_cohort",
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {"type": "person", "key": "email", "operator": "exact", "value": "test@example.com"},
                        {"type": "cohort", "key": "id", "value": unsupported_cohort.id},
                    ],
                }
            },
        )

        # Create another cohort that only has realtime-capable filters
        realtime_cohort = Cohort.objects.create(team=team, name="fully_realtime", filters=_make_person_only_filters())

        # Run command
        call_command("resave_cohorts", team_id=team.id)

        # Reload cohorts
        unsupported_cohort.refresh_from_db()
        dependent_cohort.refresh_from_db()
        realtime_cohort.refresh_from_db()

        # Assertions:
        # 1. Unsupported cohort should NOT be realtime
        assert unsupported_cohort.cohort_type is None

        # 2. Dependent cohort should NOT be realtime (blocked by dependency)
        assert dependent_cohort.cohort_type is None

        # 3. Realtime cohort should be realtime (no problematic dependencies)
        assert realtime_cohort.cohort_type == "realtime"

    def test_cohort_with_multiple_leaf_dependencies_can_be_realtime(self):
        """Test that a cohort referencing multiple leaf cohorts (no dependencies) can be realtime."""
        team: Team = self.team

        # Create two cohorts with realtime-capable filters (no dependencies)
        leaf_cohort1 = Cohort.objects.create(
            team=team, name="leaf_cohort_1", filters=_make_person_only_filters(email="user1@example.com")
        )

        leaf_cohort2 = Cohort.objects.create(
            team=team, name="leaf_cohort_2", filters=_make_person_only_filters(email="user2@example.com")
        )

        # Create a cohort that references both leaf cohorts
        multi_ref_cohort = Cohort.objects.create(
            team=team,
            name="multi_ref_cohort",
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {"type": "cohort", "key": "id", "value": leaf_cohort1.id},
                        {"type": "cohort", "key": "id", "value": leaf_cohort2.id},
                    ],
                }
            },
        )

        # Run command
        call_command("resave_cohorts", team_id=team.id)

        # Reload cohorts
        leaf_cohort1.refresh_from_db()
        leaf_cohort2.refresh_from_db()
        multi_ref_cohort.refresh_from_db()

        # Assertions:
        # 1. Both leaf cohorts should be realtime
        assert leaf_cohort1.cohort_type == "realtime"
        assert leaf_cohort2.cohort_type == "realtime"

        # 2. Multi-reference cohort CAN be realtime (references only leaf cohorts)
        assert multi_ref_cohort.cohort_type == "realtime"

    def test_cohort_with_realtime_dependency_can_be_realtime(self):
        """Test that a cohort referencing a realtime cohort can be realtime."""
        team: Team = self.team

        # Create a cohort with realtime-capable filters
        realtime_dependency = Cohort.objects.create(
            team=team,
            name="realtime_dependency",
            filters=_make_person_only_filters(),  # This can be realtime
        )

        # Create a cohort that references the realtime dependency
        dependent_cohort = Cohort.objects.create(
            team=team,
            name="dependent_cohort",
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {"type": "person", "key": "name", "operator": "exact", "value": "Test User"},
                        {"type": "cohort", "key": "id", "value": realtime_dependency.id},
                    ],
                }
            },
        )

        # Run command
        call_command("resave_cohorts", team_id=team.id)

        # Reload cohorts
        realtime_dependency.refresh_from_db()
        dependent_cohort.refresh_from_db()

        # Assertions:
        # 1. Dependency cohort should be realtime
        assert realtime_dependency.cohort_type == "realtime"

        # 2. Dependent cohort should also be realtime (dependency is realtime)
        assert dependent_cohort.cohort_type == "realtime"

    def test_cohort_with_unchanged_non_realtime_dependency_blocks_realtime(self):
        """Test that a cohort referencing an already-correct non-realtime cohort cannot be realtime.
        This catches a bug where in-memory cohort_type wasn't updated for unchanged cohorts,
        causing dependent cohorts to see stale values.
        """
        team: Team = self.team

        # Create a cohort with unsupported filters and ALREADY set as non-realtime
        non_realtime_dep = Cohort.objects.create(
            team=team,
            name="already_non_realtime",
            filters=_make_unsupported_filters(),
            cohort_type=None,  # Already correctly set to None (non-realtime)
        )

        # Create a cohort that references the non-realtime cohort
        # This cohort would be realtime on its own, but should be blocked
        dependent_cohort = Cohort.objects.create(
            team=team,
            name="dependent_on_non_realtime",
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {"type": "person", "key": "email", "operator": "exact", "value": "test@example.com"},
                        {"type": "cohort", "key": "id", "value": non_realtime_dep.id},
                    ],
                }
            },
        )

        # Run command
        call_command("resave_cohorts", team_id=team.id)

        # Reload cohorts
        non_realtime_dep.refresh_from_db()
        dependent_cohort.refresh_from_db()

        # The non-realtime cohort should remain unchanged (no will_change)
        assert non_realtime_dep.cohort_type is None

        # CRITICAL: The dependent cohort should NOT be realtime
        # This would fail with the bug where in-memory cohort_type wasn't updated
        assert dependent_cohort.cohort_type is None, (
            "Bug detected: Dependent cohort became realtime even though it references "
            "a non-realtime cohort. The in-memory cohort_type likely wasn't updated "
            "for unchanged cohorts."
        )

    def test_cohort_referencing_non_leaf_cannot_be_realtime(self):
        """Test that a cohort referencing a non-leaf cohort (B->C) cannot be realtime."""
        team: Team = self.team

        # Create base cohort C (realtime capable, leaf)
        cohort_c = Cohort.objects.create(
            team=team, name="cohort_c", filters=_make_person_only_filters(email="c@example.com")
        )

        # Create cohort B that references C (non-leaf)
        cohort_b = Cohort.objects.create(
            team=team,
            name="cohort_b",
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {"type": "cohort", "key": "id", "value": cohort_c.id},
                        {"type": "person", "key": "name", "operator": "exact", "value": "B User"},
                    ],
                }
            },
        )

        # Create cohort A that references B (B has dependencies, so A cannot be realtime)
        cohort_a = Cohort.objects.create(
            team=team,
            name="cohort_a",
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {"type": "cohort", "key": "id", "value": cohort_b.id},
                        {"type": "person", "key": "name", "operator": "exact", "value": "A User"},
                    ],
                }
            },
        )

        # Run command
        call_command("resave_cohorts", team_id=team.id)

        # Reload cohorts
        cohort_a.refresh_from_db()
        cohort_b.refresh_from_db()
        cohort_c.refresh_from_db()

        # Assertions:
        # 1. Base cohort C can be realtime (no dependencies)
        assert cohort_c.cohort_type == "realtime"

        # 2. Cohort B can be realtime (references only leaf cohort C)
        assert cohort_b.cohort_type == "realtime"

        # 3. Cohort A cannot be realtime (references B which has dependencies)
        assert cohort_a.cohort_type is None


class TestResaveCohortsCommandTwoTeams(BaseTest):
    def test_resave_two_teams_each_five_types(self):
        team_a: Team = self.team
        team_b: Team = Team.objects.create(organization=self.organization)

        # Refs for cohort-filter per team
        ref_a = Cohort.objects.create(team=team_a, name="ref_a", is_static=True)
        ref_b = Cohort.objects.create(team=team_b, name="ref_b", is_static=True)

        def make_five(team: Team, ref: Cohort) -> list[Cohort]:
            return [
                Cohort.objects.create(team=team, name=f"rt_{team.id}_1", filters=_make_realtime_filters()),
                Cohort.objects.create(team=team, name=f"uns_{team.id}_1", filters=_make_unsupported_filters()),
                Cohort.objects.create(team=team, name=f"p_{team.id}_1", filters=_make_person_only_filters()),
                Cohort.objects.create(
                    team=team,
                    name=f"cf_{team.id}_1",
                    filters={
                        "properties": {
                            "type": "AND",
                            "values": [
                                {"type": "cohort", "key": "id", "value": ref.id},
                            ],
                        }
                    },
                ),
                Cohort.objects.create(
                    team=team,
                    name=f"rt_{team.id}_2",
                    filters={
                        "properties": {
                            "type": "AND",
                            "values": [
                                {
                                    "type": "behavioral",
                                    "key": "page_view",
                                    "value": "performed_event",
                                    "event_type": "events",
                                },
                            ],
                        }
                    },
                ),
            ]

        cohorts_a = make_five(team_a, ref_a)
        cohorts_b = make_five(team_b, ref_b)

        # Run for team A only
        call_command("resave_cohorts", team_id=team_a.id)

        for c in cohorts_a:
            c.refresh_from_db()
        for c in cohorts_b:
            c.refresh_from_db()

        # Team A cohorts updated according to types
        assert cohorts_a[0].cohort_type == "realtime"
        assert cohorts_a[1].cohort_type is None
        assert cohorts_a[2].cohort_type == "realtime"
        assert cohorts_a[3].cohort_type == "realtime"
        assert cohorts_a[4].cohort_type == "realtime"

        # Team B untouched (no inline bytecode yet)
        assert not _has_condition_hash(cohorts_b[0].filters)
        assert not _has_condition_hash(cohorts_b[1].filters)
        assert not _has_condition_hash(cohorts_b[2].filters)
        assert not _has_condition_hash(cohorts_b[3].filters)
        assert not _has_condition_hash(cohorts_b[4].filters)

        # Now run for all
        call_command("resave_cohorts", batch_size=200, dry_run=False, team_id=None)  # will default to all

        for c in cohorts_b:
            c.refresh_from_db()
        assert cohorts_b[0].cohort_type == "realtime"
        assert cohorts_b[1].cohort_type is None
        assert cohorts_b[2].cohort_type == "realtime"
        assert cohorts_b[3].cohort_type == "realtime"
        assert cohorts_b[4].cohort_type == "realtime"
