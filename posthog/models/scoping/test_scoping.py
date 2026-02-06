from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.models.scoping import (
    get_current_team_id,
    reset_current_team_id,
    set_current_team_id,
    team_scope,
    unscoped,
    with_team_scope,
)


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


class TestWithTeamScopeDecorator(BaseTest):
    def test_sets_team_id_from_kwarg(self):
        """Decorator extracts team_id from keyword argument."""
        captured_team_id = None

        @with_team_scope()
        def my_task(team_id: int, other: str):
            nonlocal captured_team_id
            captured_team_id = get_current_team_id()

        my_task(team_id=42, other="test")
        assert captured_team_id == 42
        # Context should be cleaned up after function returns
        assert get_current_team_id() is None

    def test_sets_team_id_from_positional_arg(self):
        """Decorator extracts team_id from positional argument."""
        captured_team_id = None

        @with_team_scope()
        def my_task(team_id: int, other: str):
            nonlocal captured_team_id
            captured_team_id = get_current_team_id()

        my_task(42, "test")
        assert captured_team_id == 42

    def test_custom_param_name(self):
        """Decorator supports custom parameter names."""
        captured_team_id = None

        @with_team_scope(team_id_param="project_team_id")
        def my_task(project_team_id: int, other: str):
            nonlocal captured_team_id
            captured_team_id = get_current_team_id()

        my_task(project_team_id=99, other="test")
        assert captured_team_id == 99

    def test_raises_if_param_not_found(self):
        """Decorator raises ValueError if team_id param is missing."""
        import pytest

        @with_team_scope()
        def my_task(other: str):
            pass

        with pytest.raises(ValueError, match="team_id"):
            my_task(other="test")

    def test_cleans_up_on_exception(self):
        """Decorator cleans up context even if function raises."""

        @with_team_scope()
        def my_task(team_id: int):
            raise ValueError("task error")

        try:
            my_task(team_id=42)
        except ValueError:
            pass

        assert get_current_team_id() is None

    def test_preserves_function_metadata(self):
        """Decorator preserves function name and docstring."""

        @with_team_scope()
        def my_documented_task(team_id: int):
            """This is my docstring."""
            pass

        assert my_documented_task.__name__ == "my_documented_task"
        assert my_documented_task.__doc__ == "This is my docstring."

    def test_returns_function_result(self):
        """Decorator returns the function's return value."""

        @with_team_scope()
        def my_task(team_id: int) -> str:
            return f"result for team {team_id}"

        result = my_task(team_id=42)
        assert result == "result for team 42"
