import pytest

from django.contrib import admin

from posthog.admin import inline_registry
from posthog.admin.inline_registry import extra_inlines_for, register_admin_inline
from posthog.models import Organization, Team


class _DummyInline(admin.TabularInline):
    model = Organization


@pytest.fixture(autouse=True)
def _restore_registry():
    saved = {model: list(inlines) for model, inlines in inline_registry._extra_inlines.items()}
    yield
    inline_registry._extra_inlines.clear()
    inline_registry._extra_inlines.update(saved)


def test_register_admin_inline_is_idempotent():
    register_admin_inline(Organization, _DummyInline)
    register_admin_inline(Organization, _DummyInline)
    assert extra_inlines_for(Organization).count(_DummyInline) == 1


def test_inline_is_scoped_to_its_parent_model():
    register_admin_inline(Organization, _DummyInline)
    assert _DummyInline in extra_inlines_for(Organization)
    assert _DummyInline not in extra_inlines_for(Team)
