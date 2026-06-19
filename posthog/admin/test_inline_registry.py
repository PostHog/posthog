import pytest

from posthog.admin import inline_registry
from posthog.admin.inline_registry import extra_inlines_for, register_admin_inline


@pytest.fixture(autouse=True)
def _restore_registry():
    saved = {model: list(inlines) for model, inlines in inline_registry._extra_inlines.items()}
    yield
    inline_registry._extra_inlines.clear()
    inline_registry._extra_inlines.update(saved)


def test_register_admin_inline_is_idempotent():
    class _DummyModel:
        pass

    class _Inline:
        pass

    register_admin_inline(_DummyModel, _Inline)
    register_admin_inline(_DummyModel, _Inline)
    assert extra_inlines_for(_DummyModel) == [_Inline]


def test_extra_inlines_for_unregistered_model_is_empty():
    class _Unregistered:
        pass

    assert extra_inlines_for(_Unregistered) == []
