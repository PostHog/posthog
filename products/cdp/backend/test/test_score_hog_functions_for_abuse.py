import pytest

from django.core.management.base import CommandError

import httpx
from parameterized import parameterized

from products.cdp.backend.test.abuse_support import TEAM_FLAG, AbuseClassificationTestCase

COMMAND = "score_hog_functions_for_abuse"


class TestScoreHogFunctionsForAbuse(AbuseClassificationTestCase):
    def setUp(self) -> None:
        super().setUp()
        # The command ignores the team flag, so saves stay unscored and only the command calls the gateway.
        self.flags.enabled[TEAM_FLAG] = False

    def test_prints_a_row_of_scores_for_each_enabled_function_without_capturing(self) -> None:
        hog_function = self.create_destination()

        output = self.run_command(COMMAND, "--team-id", str(self.team.id))

        assert len(self.gateway.requests) == 1
        [header, row] = output.strip().split("\n")
        assert header.split("\t")[:6] == ["hog_function_id", "type", "template_id", "verdict", "risk", "rules"]
        assert row.split("\t")[:6] == [str(hog_function.id), "destination", "-", "would_block", "0.80", "internal_host"]
        assert self.captured_events() == []

    def test_scores_only_the_given_ids(self) -> None:
        chosen = self.create_destination()
        other = self.create_destination()

        output = self.run_command(COMMAND, "--id", str(chosen.id))

        assert len(self.gateway.requests) == 1
        assert str(chosen.id) in output
        assert str(other.id) not in output

    def test_capture_reports_each_verdict_as_an_eval_event(self) -> None:
        hog_function = self.create_destination()

        self.run_command(COMMAND, "--id", str(hog_function.id), "--capture")

        [event] = self.captured_events()
        assert event["properties"]["trigger"] == "eval"
        assert event["properties"]["hog_function_id"] == str(hog_function.id)
        assert "backfill_run_id" not in event["properties"]

    def test_a_failed_function_prints_its_error_and_the_run_continues(self) -> None:
        self.create_destination()
        self.create_destination()
        self.gateway.response = httpx.Response(503, json={"error": "busy"})

        output = self.run_command(COMMAND, "--team-id", str(self.team.id))

        assert len(self.gateway.requests) == 2
        assert output.count("error:gateway_error\t-\tinternal_host") == 2

    @parameterized.expand([("by_default", [], 0), ("with_include_disabled", ["--include-disabled"], 1)])
    def test_a_disabled_function_is_scored_only_when_asked(
        self, _name: str, options: list[str], expected_requests: int
    ) -> None:
        disabled = self.create_destination(enabled=False)

        output = self.run_command(COMMAND, "--id", str(disabled.id), *options)

        assert len(self.gateway.requests) == expected_requests
        assert (str(disabled.id) in output) == bool(expected_requests)

    def test_needs_ids_or_a_team(self) -> None:
        with pytest.raises(CommandError, match="--id or --team-id"):
            self.run_command(COMMAND)

    def test_skips_a_transformation_that_runs_template_code(self) -> None:
        stock = self.create_from_template(self.create_template("transformation"))

        output = self.run_command(COMMAND, "--id", str(stock.id))

        assert self.gateway.requests == []
        assert str(stock.id) not in output
