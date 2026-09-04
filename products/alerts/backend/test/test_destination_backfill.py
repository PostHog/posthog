from typing import Any
from uuid import uuid4

from posthog.test.base import BaseTest

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.team.team import Team

from products.alerts.backend.destination_backfill import (
    INSIGHT_CHART_BLOCK,
    backfill_insight_alert_chart_blocks,
    blocks_with_chart,
)
from products.cdp.backend.models.hog_functions.hog_function import HogFunction

HEADER_BLOCK = {"type": "header", "text": {"type": "plain_text", "text": "Alert firing"}}
CONTEXT_BLOCK = {"type": "context", "elements": [{"type": "mrkdwn", "text": "Project"}]}
ACTIONS_BLOCK = {"type": "actions", "elements": [{"type": "button", "url": "{project.url}"}]}

PRE_CHART_BLOCKS = [HEADER_BLOCK, CONTEXT_BLOCK, {"type": "divider"}, ACTIONS_BLOCK]


SLACK_INPUTS_SCHEMA = [
    {"key": "slack_workspace", "type": "integration"},
    {"key": "channel", "type": "string"},
    {"key": "blocks", "type": "json"},
]


def _inputs(destination: HogFunction) -> dict[str, Any]:
    inputs = destination.inputs
    assert inputs is not None
    return inputs


def slack_inputs(blocks: list[Any]) -> dict[str, Any]:
    return {
        "blocks": {"value": blocks, "bytecode": ["_H", 1], "order": 0},
        "channel": {"value": "C-ENG", "order": 1},
        "slack_workspace": {"value": 1, "order": 2},
    }


class TestBlocksWithChart(SimpleTestCase):
    @parameterized.expand(
        [
            ("no divider above the buttons", [HEADER_BLOCK, CONTEXT_BLOCK, ACTIONS_BLOCK]),
            ("divider is not the last block before the buttons", [{"type": "divider"}, CONTEXT_BLOCK, ACTIONS_BLOCK]),
            ("divider carries extra keys", [{"type": "divider", "block_id": "mine"}, ACTIONS_BLOCK]),
            ("no buttons at all", [HEADER_BLOCK, {"type": "divider"}]),
            (
                "a chart was added by hand",
                [
                    {"type": "image", "image_url": "{event.properties.insight_chart_url}", "alt_text": "Chart"},
                    {"type": "divider"},
                    ACTIONS_BLOCK,
                ],
            ),
            ("buttons come first", [ACTIONS_BLOCK, {"type": "divider"}]),
            ("blocks are not a list", {"type": "divider"}),
            ("blocks are missing", None),
        ]
    )
    def test_leaves_blocks_it_does_not_recognize_alone(self, _name: str, blocks: Any) -> None:
        assert blocks_with_chart(blocks) is None

    def test_replaces_the_divider_directly_above_the_buttons(self) -> None:
        assert blocks_with_chart(PRE_CHART_BLOCKS) == [
            HEADER_BLOCK,
            CONTEXT_BLOCK,
            INSIGHT_CHART_BLOCK,
            ACTIONS_BLOCK,
        ]

    def test_a_repaired_destination_is_no_longer_a_candidate(self) -> None:
        assert blocks_with_chart(blocks_with_chart(PRE_CHART_BLOCKS)) is None


class TestBackfillInsightAlertChartBlocks(BaseTest):
    def _destination(
        self,
        *,
        blocks: list[Any] | None = None,
        template_id: str = "template-slack",
        event_id: str = "$insight_alert_firing",
        deleted: bool = False,
        team: Team | None = None,
    ) -> HogFunction:
        return HogFunction.objects.create(
            team=team or self.team,
            name="Alert → Slack",
            type="internal_destination",
            hog="return 1",
            enabled=True,
            deleted=deleted,
            template_id=template_id,
            inputs_schema=SLACK_INPUTS_SCHEMA,
            inputs=slack_inputs(blocks if blocks is not None else list(PRE_CHART_BLOCKS)),
            filters={
                "events": [{"id": event_id, "type": "events"}],
                "properties": [{"key": "alert_id", "value": str(uuid4()), "operator": "exact", "type": "event"}],
            },
        )

    def _stored_blocks(self, destination: HogFunction) -> Any:
        destination.refresh_from_db()
        return _inputs(destination)["blocks"]

    def test_apply_rewrites_the_blocks_and_their_bytecode(self) -> None:
        destination = self._destination()

        with self.captureOnCommitCallbacks(execute=True):
            result = backfill_insight_alert_chart_blocks(apply=True)

        assert (result.scanned, result.repaired, result.already_current, result.left_alone) == (1, 1, 0, 0)
        stored = self._stored_blocks(destination)
        assert stored["value"][2] == INSIGHT_CHART_BLOCK
        # A value written without a matching recompile would keep posting the old blocks.
        assert stored["bytecode"] != ["_H", 1]
        assert stored["order"] == 0

    def test_dry_run_reports_the_work_without_doing_it(self) -> None:
        destination = self._destination()

        result = backfill_insight_alert_chart_blocks()

        assert result.repaired == 1
        assert self._stored_blocks(destination)["value"] == PRE_CHART_BLOCKS

    def test_running_it_twice_changes_nothing_the_second_time(self) -> None:
        self._destination()

        with self.captureOnCommitCallbacks(execute=True):
            backfill_insight_alert_chart_blocks(apply=True)
            second = backfill_insight_alert_chart_blocks(apply=True)

        assert (second.scanned, second.repaired, second.already_current) == (1, 0, 1)

    def test_hand_edited_blocks_are_counted_but_not_written(self) -> None:
        custom = [HEADER_BLOCK, ACTIONS_BLOCK]
        destination = self._destination(blocks=custom)

        with self.captureOnCommitCallbacks(execute=True):
            result = backfill_insight_alert_chart_blocks(apply=True)

        assert (result.repaired, result.left_alone) == (0, 1)
        assert self._stored_blocks(destination)["value"] == custom

    def test_liquid_templated_blocks_are_left_alone(self) -> None:
        # A hog expression in liquid blocks would reach Slack as literal text.
        destination = self._destination()
        _inputs(destination)["blocks"]["templating"] = "liquid"
        destination.save(update_fields=["inputs"])

        with self.captureOnCommitCallbacks(execute=True):
            result = backfill_insight_alert_chart_blocks(apply=True)

        assert (result.repaired, result.left_alone) == (0, 1)
        assert self._stored_blocks(destination)["value"] == PRE_CHART_BLOCKS

    @parameterized.expand(
        [
            ("a webhook destination", {"template_id": "template-webhook"}),
            ("a Slack destination for another alert product", {"event_id": "$logs_alert_firing"}),
            ("a deleted destination", {"deleted": True}),
        ]
    )
    def test_skips(self, _name: str, overrides: dict[str, Any]) -> None:
        self._destination(**overrides)

        result = backfill_insight_alert_chart_blocks()

        assert result.scanned == 0

    def test_one_destination_that_will_not_compile_does_not_stop_the_sweep(self) -> None:
        # A hyphenated property is the everyday way an edited block stops compiling.
        broken_header = {"type": "header", "text": {"type": "plain_text", "text": "{event.properties.some-prop}"}}
        broken = self._destination(blocks=[broken_header, {"type": "divider"}, ACTIONS_BLOCK])
        healthy = self._destination()

        with self.captureOnCommitCallbacks(execute=True):
            result = backfill_insight_alert_chart_blocks(apply=True)

        assert (result.scanned, result.repaired, result.uncompilable) == (2, 1, 1)
        assert self._stored_blocks(healthy)["value"][2] == INSIGHT_CHART_BLOCK
        assert self._stored_blocks(broken)["value"][1] == {"type": "divider"}

    def test_limit_caps_how_many_destinations_the_sweep_touches(self) -> None:
        self._destination()
        self._destination()

        with self.captureOnCommitCallbacks(execute=True):
            result = backfill_insight_alert_chart_blocks(limit=1, apply=True)

        assert (result.scanned, result.repaired) == (1, 1)

    def test_team_ids_narrows_the_backfill(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other")
        mine = self._destination()
        theirs = self._destination(team=other_team)

        with self.captureOnCommitCallbacks(execute=True):
            result = backfill_insight_alert_chart_blocks(team_ids=[self.team.id], apply=True)

        assert (result.scanned, result.repaired) == (1, 1)
        assert self._stored_blocks(mine)["value"][2] == INSIGHT_CHART_BLOCK
        assert self._stored_blocks(theirs)["value"] == PRE_CHART_BLOCKS
