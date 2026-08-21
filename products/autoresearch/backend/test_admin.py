from django.contrib import admin
from django.test import SimpleTestCase

from parameterized import parameterized

from products.autoresearch.backend import admin as autoresearch_admin
from products.autoresearch.backend.models import AutoresearchPipeline

AUTORESEARCH_ADMINS = [
    (model.__name__, model, model_admin)
    for model, model_admin in admin.site._registry.items()
    if model.__module__ == AutoresearchPipeline.__module__
]

INLINES = [
    (inline.__name__, inline)
    for inline in vars(autoresearch_admin).values()
    if isinstance(inline, type) and issubclass(inline, admin.options.InlineModelAdmin)
]


class TestAdminReadsOutsideTeamScope(SimpleTestCase):
    # Every autoresearch model is fail-closed, and TeamScopedRootMixin leaves
    # _default_manager bound to the scoped manager. Admin has no team context, so an
    # admin that inherits Django's get_queryset raises TeamScopeError and the page 500s.

    def test_every_autoresearch_model_is_registered_in_admin(self) -> None:
        assert len(AUTORESEARCH_ADMINS) == 6

    @parameterized.expand(AUTORESEARCH_ADMINS)
    def test_admin_queryset_does_not_need_team_context(self, _name, _model, model_admin) -> None:
        model_admin.get_queryset(request=None)

    @parameterized.expand(INLINES)
    def test_inline_queryset_does_not_need_team_context(self, _name, inline) -> None:
        inline.get_queryset(inline, request=None)
