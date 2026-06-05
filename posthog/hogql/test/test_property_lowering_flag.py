"""The `propertyLowering` modifier + org feature flag that controls which property path *serves* (printer rearch §13).

Off (unset) keeps the legacy printer path; on switches the org to the new lowering path. Verified two ways: the
modifier maps onto the context gate at the single compile entry point, and the org flag sets the modifier (and leaves
it unset — not False — when off, so it never overrides an explicit gate).
"""

from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.schema import HogQLQueryModifiers

from posthog.hogql.context import HogQLContext
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_ast_for_printing


class TestPropertyLoweringFlag(BaseTest):
    def _context(self, **modifier_kwargs) -> HogQLContext:
        return HogQLContext(
            team_id=self.team.pk,
            team=self.team,
            enable_select_queries=True,
            modifiers=HogQLQueryModifiers(**modifier_kwargs),
        )

    def test_modifier_on_flips_the_context_gate(self) -> None:
        context = self._context(propertyLowering=True)
        prepare_ast_for_printing(parse_select("SELECT properties.foo FROM events"), context, "clickhouse")
        assert context.lower_property_access is True

    def test_modifier_unset_leaves_the_legacy_path(self) -> None:
        context = self._context()
        prepare_ast_for_printing(parse_select("SELECT properties.foo FROM events"), context, "clickhouse")
        assert context.lower_property_access is False

    @patch("posthog.hogql.modifiers.is_cloud", return_value=True)
    @patch("posthog.hogql.modifiers.posthoganalytics.feature_enabled")
    def test_org_flag_enabled_sets_modifier_true(self, mock_flag, _mock_cloud) -> None:
        mock_flag.return_value = True
        assert create_default_modifiers_for_team(self.team).propertyLowering is True

    @patch("posthog.hogql.modifiers.is_cloud", return_value=True)
    @patch("posthog.hogql.modifiers.posthoganalytics.feature_enabled")
    def test_org_flag_disabled_leaves_modifier_unset(self, mock_flag, _mock_cloud) -> None:
        # Off must stay None (not False) so it never overrides an explicitly-set gate.
        mock_flag.return_value = False
        assert create_default_modifiers_for_team(self.team).propertyLowering is None

    @patch("posthog.hogql.modifiers.is_cloud", return_value=False)
    @patch("posthog.hogql.modifiers.posthoganalytics.feature_enabled")
    def test_org_flag_not_evaluated_off_cloud(self, mock_flag, _mock_cloud) -> None:
        # Off-Cloud the flag is never evaluated: the modifier stays unset and feature_enabled is not called, so the
        # per-org rollout never touches the broadly-invoked, widely-mocked modifier path outside Cloud.
        assert create_default_modifiers_for_team(self.team).propertyLowering is None
        mock_flag.assert_not_called()
