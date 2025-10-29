from __future__ import annotations

from typing import Any

from posthog.test.base import BaseTest

from django.core.management import call_command

from posthog.models.cohort.cohort import Cohort
from posthog.models.team.team import Team


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

        # Ensure initial state has no compiled bytecode
        for c in cohorts:
            assert c.compiled_bytecode is None
            assert c.cohort_type is None

        # Run command for this team
        call_command("resave_cohorts", team_id=team.id)

        # Reload and assert
        updated = {c.id: Cohort.objects.get(id=c.id) for c in cohorts}

        # realtime-capable
        assert updated[cohorts[0].id].cohort_type == "realtime"
        assert updated[cohorts[0].id].compiled_bytecode is not None

        # unsupported stays None
        assert updated[cohorts[1].id].cohort_type is None
        # some supported filters in there still produce bytecode entries
        assert updated[cohorts[1].id].compiled_bytecode is not None

        # person-only is realtime-capable
        assert updated[cohorts[2].id].cohort_type == "realtime"
        assert updated[cohorts[2].id].compiled_bytecode is not None

        # cohort filter is realtime-capable
        assert updated[cohorts[3].id].cohort_type == "realtime"
        assert updated[cohorts[3].id].compiled_bytecode is not None

        # simple behavioral realtime
        assert updated[cohorts[4].id].cohort_type == "realtime"
        assert updated[cohorts[4].id].compiled_bytecode is not None


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

        # Team B untouched
        assert cohorts_b[0].compiled_bytecode is None
        assert cohorts_b[1].compiled_bytecode is None
        assert cohorts_b[2].compiled_bytecode is None
        assert cohorts_b[3].compiled_bytecode is None
        assert cohorts_b[4].compiled_bytecode is None

        # Now run for all
        call_command("resave_cohorts", batch_size=200, dry_run=False, team_id=None)  # will default to all

        for c in cohorts_b:
            c.refresh_from_db()
        assert cohorts_b[0].cohort_type == "realtime"
        assert cohorts_b[1].cohort_type is None
        assert cohorts_b[2].cohort_type == "realtime"
        assert cohorts_b[3].cohort_type == "realtime"
        assert cohorts_b[4].cohort_type == "realtime"
