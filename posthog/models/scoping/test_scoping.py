from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.models.scoping import get_current_team_id, reset_current_team_id, set_current_team_id, team_scope, unscoped


class TestContextVar(BaseTest):
    def test_default_is_none(self):
        assert get_current_team_id() is None

    def test_set_and_get(self):
        token = set_current_team_id(42)
        try:
            assert get_current_team_id() == 42
        finally:
            reset_current_team_id(token)

    def test_reset_restores_previous_value(self):
        token1 = set_current_team_id(1)
        try:
            token2 = set_current_team_id(2)
            assert get_current_team_id() == 2
            reset_current_team_id(token2)
            assert get_current_team_id() == 1
        finally:
            reset_current_team_id(token1)

    def test_reset_to_none(self):
        token = set_current_team_id(99)
        reset_current_team_id(token)
        assert get_current_team_id() is None


class TestTeamScopeContextManager(BaseTest):
    @parameterized.expand(
        [
            (1,),
            (42,),
            (999,),
        ]
    )
    def test_sets_team_id(self, team_id: int):
        assert get_current_team_id() is None
        with team_scope(team_id):
            assert get_current_team_id() == team_id
        assert get_current_team_id() is None

    def test_nested_scopes(self):
        with team_scope(1):
            assert get_current_team_id() == 1
            with team_scope(2):
                assert get_current_team_id() == 2
                with team_scope(3):
                    assert get_current_team_id() == 3
                assert get_current_team_id() == 2
            assert get_current_team_id() == 1
        assert get_current_team_id() is None

    def test_cleans_up_on_exception(self):
        try:
            with team_scope(123):
                assert get_current_team_id() == 123
                raise ValueError("test exception")
        except ValueError:
            pass
        assert get_current_team_id() is None

    def test_nested_cleanup_on_exception(self):
        with team_scope(1):
            try:
                with team_scope(2):
                    raise ValueError("inner exception")
            except ValueError:
                pass
            # Should restore to outer scope
            assert get_current_team_id() == 1
        assert get_current_team_id() is None


class TestUnscopedContextManager(BaseTest):
    def test_clears_team_id(self):
        with team_scope(42):
            assert get_current_team_id() == 42
            with unscoped():
                assert get_current_team_id() is None
            assert get_current_team_id() == 42

    def test_works_without_existing_scope(self):
        assert get_current_team_id() is None
        with unscoped():
            assert get_current_team_id() is None
        assert get_current_team_id() is None

    def test_nested_unscoped(self):
        with team_scope(1):
            with unscoped():
                assert get_current_team_id() is None
                with team_scope(2):
                    assert get_current_team_id() == 2
                assert get_current_team_id() is None
            assert get_current_team_id() == 1

    def test_cleans_up_on_exception(self):
        with team_scope(99):
            try:
                with unscoped():
                    assert get_current_team_id() is None
                    raise ValueError("test")
            except ValueError:
                pass
            assert get_current_team_id() == 99
