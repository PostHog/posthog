import pytest

from django.db import IntegrityError

from parameterized import parameterized

from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.models.user_repo_preference import UserRepoPreference


class TestUserRepoPreference:
    @pytest.fixture(autouse=True)
    def setup(self, db):
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create(email="test@example.com", distinct_id="user-1")

    def test_get_default_returns_none_when_no_preference(self):
        result = UserRepoPreference.get_default(
            self.team.id,
            self.user.id,
            UserRepoPreference.ScopeType.SLACK_CHANNEL,
            "C001",
        )
        assert result is None

    def test_set_default_creates_then_updates(self):
        UserRepoPreference.set_default(
            self.team.id,
            self.user.id,
            UserRepoPreference.ScopeType.SLACK_CHANNEL,
            "C001",
            repository="org/repo-a",
        )
        assert (
            UserRepoPreference.get_default(
                self.team.id,
                self.user.id,
                UserRepoPreference.ScopeType.SLACK_CHANNEL,
                "C001",
            )
            == "org/repo-a"
        )

        UserRepoPreference.set_default(
            self.team.id,
            self.user.id,
            UserRepoPreference.ScopeType.SLACK_CHANNEL,
            "C001",
            repository="org/repo-b",
        )
        assert (
            UserRepoPreference.get_default(
                self.team.id,
                self.user.id,
                UserRepoPreference.ScopeType.SLACK_CHANNEL,
                "C001",
            )
            == "org/repo-b"
        )
        assert UserRepoPreference.objects.filter(team=self.team, user=self.user).count() == 1

    @parameterized.expand(
        [
            ("exists", True, True),
            ("not_exists", False, False),
        ]
    )
    def test_clear_default(self, _name, create_first, expected_return):
        if create_first:
            UserRepoPreference.set_default(
                self.team.id,
                self.user.id,
                UserRepoPreference.ScopeType.SLACK_CHANNEL,
                "C001",
                repository="org/repo",
            )
        result = UserRepoPreference.clear_default(
            self.team.id,
            self.user.id,
            UserRepoPreference.ScopeType.SLACK_CHANNEL,
            "C001",
        )
        assert result is expected_return

    def test_unique_constraint_enforced(self):
        UserRepoPreference.objects.create(
            team=self.team,
            user=self.user,
            scope_type=UserRepoPreference.ScopeType.SLACK_CHANNEL,
            scope_id="C001",
            repository="org/repo-a",
        )
        with pytest.raises(IntegrityError):
            UserRepoPreference.objects.create(
                team=self.team,
                user=self.user,
                scope_type=UserRepoPreference.ScopeType.SLACK_CHANNEL,
                scope_id="C001",
                repository="org/repo-b",
            )

    @parameterized.expand(
        [
            ("none_becomes_empty", None),
            ("empty_stays_empty", ""),
        ]
    )
    def test_scope_id_none_normalization(self, _name, scope_id):
        UserRepoPreference.set_default(
            self.team.id,
            self.user.id,
            UserRepoPreference.ScopeType.SLACK_CHANNEL,
            scope_id,
            repository="org/repo",
        )
        pref = UserRepoPreference.objects.get(team=self.team, user=self.user)
        assert pref.scope_id == ""

    def test_validate_scope_type_rejects_unknown(self):
        with pytest.raises(ValueError, match="Invalid scope_type"):
            UserRepoPreference.get_default(self.team.id, self.user.id, "nonexistent_scope")

    def test_accepts_enum_value(self):
        UserRepoPreference.set_default(
            self.team.id, self.user.id, UserRepoPreference.ScopeType.SLACK_CHANNEL, "C001", repository="org/repo"
        )
        result = UserRepoPreference.get_default(
            self.team.id, self.user.id, UserRepoPreference.ScopeType.SLACK_CHANNEL, "C001"
        )
        assert result == "org/repo"
