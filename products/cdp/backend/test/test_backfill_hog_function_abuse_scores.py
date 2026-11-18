import re
from typing import Any

from unittest.mock import patch

from django.db import connection
from django.test.utils import CaptureQueriesContext

import httpx
from parameterized import parameterized

from posthog.models.organization import Organization
from posthog.models.team.team import Team

from products.cdp.backend.tasks.abuse_classification import backfill_hog_function_abuse_score
from products.cdp.backend.test.abuse_support import (
    BACKFILL_FLAG,
    RULE_FREE_HOG,
    SCORES,
    TEAM_FLAG,
    AbuseClassificationTestCase,
    decision_payload,
)

COMMAND = "backfill_hog_function_abuse_scores"
BACKFILL_MODULE = "products.cdp.backend.management.commands.backfill_hog_function_abuse_scores"
SLEEP = f"{BACKFILL_MODULE}.time.sleep"


class TestBackfillHogFunctionAbuseScores(AbuseClassificationTestCase):
    def test_a_backfill_dry_run_queues_nothing(self) -> None:
        self.flags.enabled[TEAM_FLAG] = False
        self.create_destination()
        self.create_destination()

        output = self.run_command("backfill_hog_function_abuse_scores", "--dry-run", "--rate", "0")

        assert self.gateway.requests == []
        assert "2 functions" in output

    def test_a_backfill_skips_excluded_teams_and_organizations(self) -> None:
        self.flags.enabled[TEAM_FLAG] = False
        excluded_team = Team.objects.create(organization=self.organization, name="Excluded team")
        other_organization = Organization.objects.create(name="Excluded organization")
        other_team = Team.objects.create(organization=other_organization, name="Other organization team")
        self.create_destination(team=excluded_team)
        self.create_destination(team=other_team)
        included = self.create_destination()

        self.run_command(
            "backfill_hog_function_abuse_scores",
            "--exclude-team",
            str(excluded_team.id),
            "--exclude-organization",
            str(other_organization.id),
            "--rate",
            "0",
        )

        assert [event["properties"]["hog_function_id"] for event in self.captured_events()] == [str(included.id)]

    def test_the_backfill_kill_switch_stops_the_run(self) -> None:
        self.flags.enabled[TEAM_FLAG] = False
        self.flags.enabled[BACKFILL_FLAG] = False
        hog_function = self.create_destination()

        output = self.run_command("backfill_hog_function_abuse_scores", "--rate", "0")
        backfill_hog_function_abuse_score(team_id=self.team.id, hog_function_id=str(hog_function.id), run_id="queued")

        assert self.gateway.requests == []
        assert "stopped" in output

    def test_a_backfill_rescores_a_function_and_tags_the_run(self) -> None:
        hog_function = self.create_destination()

        output = self.run_command("backfill_hog_function_abuse_scores", "--rate", "0")
        with self.committed():
            hog_function.save()

        run_id = re.search(r"run_id ([0-9a-f]+)", output)
        assert run_id is not None
        assert len(self.gateway.requests) == 2
        save_event, backfill_event = self.captured_events()
        assert save_event["properties"]["trigger"] == "save"
        assert backfill_event["properties"]["trigger"] == "backfill"
        assert backfill_event["properties"]["backfill_run_id"] == run_id.group(1)

    def test_a_resumed_backfill_run_scores_only_what_it_has_not_scored(self) -> None:
        self.flags.enabled[TEAM_FLAG] = False
        self.create_destination()
        self.create_destination()
        self.gateway.response = httpx.Response(503, json={"error": "busy"})
        output = self.run_command("backfill_hog_function_abuse_scores", "--rate", "0")
        run_id = re.search(r"run_id ([0-9a-f]+)", output)
        assert run_id is not None
        self.gateway.response = httpx.Response(200, json=decision_payload(SCORES))

        for _ in range(2):
            self.run_command("backfill_hog_function_abuse_scores", "--run-id", run_id.group(1), "--rate", "0")

        assert len(self.gateway.requests) == 4
        assert {event["properties"]["backfill_run_id"] for event in self.captured_events()} == {run_id.group(1)}

    def test_never_scores_a_disabled_function(self) -> None:
        self.flags.enabled[TEAM_FLAG] = False
        self.create_destination()
        disabled = self.create_destination(enabled=False)

        self.run_command(COMMAND, "--rate", "0")

        assert len(self.gateway.requests) == 1
        assert str(disabled.id) not in "".join(self.gateway.bodies())

    @parameterized.expand([("limit", ["--limit", "2"], [0, 1]), ("after_id", ["--after-id", "{first}"], [1, 2])])
    def test_limit_and_after_id_select_a_slice_in_id_order(
        self, _name: str, options: list[str], expected: list[int]
    ) -> None:
        self.flags.enabled[TEAM_FLAG] = False
        ids = sorted(str(self.create_destination().id) for _ in range(3))

        self.run_command(COMMAND, *(option.format(first=ids[0]) for option in options), "--rate", "0")

        assert sorted(event["properties"]["hog_function_id"] for event in self.captured_events()) == [
            ids[index] for index in expected
        ]

    def test_rate_spaces_out_the_queued_tasks(self) -> None:
        self.flags.enabled[TEAM_FLAG] = False
        self.create_destination()
        self.create_destination()
        clock = [0.0]
        queued_at: list[float] = []
        record = self.capture.record

        def advance(seconds: float) -> None:
            clock[0] += seconds

        def record_with_time(**event: Any) -> None:
            queued_at.append(clock[0])
            record(**event)

        with patch(SLEEP, new=advance), patch.object(self.capture, "record", new=record_with_time):
            self.run_command(COMMAND, "--rate", "4")

        assert queued_at == [0.0, 0.25]

    def test_skips_transformations_that_run_template_code(self) -> None:
        self.flags.enabled[TEAM_FLAG] = False
        self.create_from_template(self.create_template("transformation"))
        custom = self.create_destination(type="transformation")

        dry_run = self.run_command(COMMAND, "--dry-run", "--rate", "0")
        self.run_command(COMMAND, "--rate", "0")

        assert "1 functions" in dry_run
        assert [event["properties"]["hog_function_id"] for event in self.captured_events()] == [str(custom.id)]

    def test_scores_teams_outside_the_flag_with_the_flag_thresholds(self) -> None:
        self.flags.enabled[TEAM_FLAG] = False
        self.flags.payload = {"alert_threshold": 0.3, "block_threshold": 0.75}
        self.create_destination(hog=RULE_FREE_HOG)

        self.run_command(COMMAND, "--rate", "0")

        [event] = self.captured_events()
        assert event["properties"]["would_block"] is True

    def test_reads_candidates_across_pages(self) -> None:
        self.flags.enabled[TEAM_FLAG] = False
        ids = sorted(str(self.create_destination().id) for _ in range(3))

        with patch(f"{BACKFILL_MODULE}._PAGE_SIZE", 1):
            self.run_command(COMMAND, "--rate", "0")

        assert sorted(event["properties"]["hog_function_id"] for event in self.captured_events()) == ids

    def test_a_dry_run_reads_candidates_without_a_query_per_function(self) -> None:
        self.flags.enabled[TEAM_FLAG] = False
        self.create_destination(type="transformation")

        def dry_run_queries() -> int:
            with CaptureQueriesContext(connection) as queries:
                self.run_command(COMMAND, "--dry-run", "--rate", "0")
            return len(queries)

        one = dry_run_queries()
        self.create_destination(type="transformation")
        self.create_destination(type="transformation")

        assert dry_run_queries() == one
