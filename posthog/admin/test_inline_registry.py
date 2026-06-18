from posthog.admin.inline_registry import extra_inlines_for, register_admin_inline


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
