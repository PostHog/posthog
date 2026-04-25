"""Unit tests for the tenant-scoped model classifier.

These run without Django bootstrap — the module only reads the semgrep
YAML.
"""

from __future__ import annotations

import unittest

from posthog.test.idor.fk_target_models import (
    ORG_SCOPED_MODELS,
    TEAM_SCOPED_MODELS,
    USER_AND_TEAM_SCOPED_MODELS,
    USER_SCOPED_MODELS,
    classify_model_scope,
)


class TestFKTargetModels(unittest.TestCase):
    def test_known_team_scoped_models_present(self) -> None:
        for name in ["Dashboard", "FeatureFlag", "Insight", "Integration", "Cohort", "BatchExport"]:
            assert name in TEAM_SCOPED_MODELS, f"{name} should be classified as team-scoped"

    def test_known_org_scoped_models_present(self) -> None:
        for name in ["OrganizationMembership", "OrganizationInvite", "Plugin", "Role"]:
            assert name in ORG_SCOPED_MODELS, f"{name} should be classified as org-scoped"

    def test_known_user_scoped_models_present(self) -> None:
        for name in ["PersonalAPIKey", "WebauthnCredential"]:
            assert name in USER_SCOPED_MODELS, f"{name} should be classified as user-scoped"

    def test_known_user_and_team_scoped_models_present(self) -> None:
        for name in ["InsightViewed", "SessionRecordingViewed"]:
            assert name in USER_AND_TEAM_SCOPED_MODELS, f"{name} should be classified as user+team scoped"

    def test_classify_team_scoped(self) -> None:
        assert classify_model_scope("Dashboard") == "team"
        assert classify_model_scope("FeatureFlag") == "team"

    def test_classify_org_scoped(self) -> None:
        assert classify_model_scope("OrganizationMembership") == "organization"

    def test_classify_user_scoped(self) -> None:
        assert classify_model_scope("PersonalAPIKey") == "user_in_org"

    def test_classify_user_and_team_scoped(self) -> None:
        assert classify_model_scope("InsightViewed") == "user_and_team"

    def test_classify_user_and_team_takes_precedence_over_team(self) -> None:
        # Some models appear in both the team-scoped set and the user+team
        # composite set (e.g. FileSystemShortcut). The composite scope is
        # stricter, so classify should prefer it.
        overlap = TEAM_SCOPED_MODELS & USER_AND_TEAM_SCOPED_MODELS
        for name in overlap:
            assert classify_model_scope(name) == "user_and_team", f"{name} should prefer user_and_team scope"

    def test_classify_unknown_model_returns_none(self) -> None:
        assert classify_model_scope("User") is None
        assert classify_model_scope("NotARealModel") is None

    def test_sets_are_non_empty(self) -> None:
        assert len(TEAM_SCOPED_MODELS) > 50, "team-scoped set should be large (100+ models today)"
        assert len(ORG_SCOPED_MODELS) >= 5
        assert len(USER_SCOPED_MODELS) >= 2
        assert len(USER_AND_TEAM_SCOPED_MODELS) >= 2


if __name__ == "__main__":
    unittest.main()
