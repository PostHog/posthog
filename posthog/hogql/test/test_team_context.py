import dataclasses
from zoneinfo import ZoneInfo

from posthog.test.base import BaseTest

from posthog.hogql.team_context import HogQLTeamContext


class TestHogQLTeamContext(BaseTest):
    def test_from_team_captures_config(self):
        self.team.timezone = "Europe/Amsterdam"
        self.team.test_account_filters = [{"key": "$browser", "value": "Chrome", "type": "event"}]
        self.team.modifiers = {"personsArgMaxVersion": "v2"}
        self.team.save()

        ctx = HogQLTeamContext.from_team(self.team)

        assert ctx.team_id == self.team.id
        assert ctx.project_id == self.team.project_id
        assert ctx.uuid == str(self.team.uuid)
        assert ctx.organization_id == str(self.team.organization_id)
        assert ctx.timezone == "Europe/Amsterdam"
        assert ctx.modifiers == {"personsArgMaxVersion": "v2"}
        assert ctx.test_account_filters == [{"key": "$browser", "value": "Chrome", "type": "event"}]

    def test_timezone_info_matches_team(self):
        self.team.timezone = "America/New_York"
        self.team.save()

        ctx = HogQLTeamContext.from_team(self.team)

        assert ctx.timezone_info == ZoneInfo("America/New_York")
        assert ctx.timezone_info == self.team.timezone_info

    def test_from_team_coerces_null_test_account_filters(self):
        self.team.test_account_filters = None  # in-memory only; the column itself is NOT NULL

        ctx = HogQLTeamContext.from_team(self.team)

        assert ctx.test_account_filters == []

    def test_constructible_without_a_team(self):
        # The point of the contract: engine code can build it with no Django model.
        ctx = HogQLTeamContext(team_id=1, project_id=1, uuid="x", organization_id="y", timezone="UTC")

        assert ctx.timezone_info == ZoneInfo("UTC")
        assert ctx.modifiers is None
        assert ctx.test_account_filters == []

    def test_is_plain_serializable_data(self):
        # Foreshadows caching / cross-process (e.g. Rust) use: the contract round-trips
        # through plain data with no Django involved.
        ctx = HogQLTeamContext(
            team_id=1,
            project_id=2,
            uuid="u",
            organization_id="o",
            timezone="UTC",
            modifiers={"personsArgMaxVersion": "v2"},
            test_account_filters=[{"k": "v"}],
        )

        as_dict = dataclasses.asdict(ctx)

        assert as_dict["team_id"] == 1
        assert as_dict["modifiers"] == {"personsArgMaxVersion": "v2"}
        assert HogQLTeamContext(**as_dict) == ctx

    def test_is_immutable(self):
        ctx = HogQLTeamContext(team_id=1, project_id=1, uuid="x", organization_id="y", timezone="UTC")

        with self.assertRaises(dataclasses.FrozenInstanceError):
            ctx.team_id = 2  # type: ignore[misc]  # ty: ignore[invalid-assignment]
