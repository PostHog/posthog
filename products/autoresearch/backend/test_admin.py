from django.contrib import admin
from django.db.models import Model
from django.http import HttpRequest
from django.test import RequestFactory, SimpleTestCase

from parameterized import parameterized

from products.autoresearch.backend import admin as _autoresearch_admin  # noqa: F401 — registers the admins
from products.autoresearch.backend.models import AutoresearchIteration, AutoresearchPipeline

AUTORESEARCH_ADMINS = [
    (model.__name__, model, model_admin)
    for model, model_admin in admin.site._registry.items()
    if model.__module__ == AutoresearchPipeline.__module__
]

AUTORESEARCH_INLINES = [
    (f"{model.__name__}.{inline.__name__}", model, inline)
    for _name, model, model_admin in AUTORESEARCH_ADMINS
    for inline in model_admin.inlines
]


def _request() -> HttpRequest:
    return RequestFactory().get("/")


class TestAdminReadsOutsideTeamScope(SimpleTestCase):
    # Every autoresearch model is fail-closed, and TeamScopedRootMixin leaves
    # _default_manager bound to the scoped manager. Admin has no team context, so an
    # admin that inherits Django's get_queryset raises TeamScopeError and the page 500s.

    def test_every_autoresearch_model_is_registered_in_admin(self) -> None:
        assert len(AUTORESEARCH_ADMINS) == 6

    @parameterized.expand(AUTORESEARCH_ADMINS)
    def test_admin_queryset_does_not_need_team_context(
        self, _name: str, _model: type[Model], model_admin: admin.ModelAdmin
    ) -> None:
        model_admin.get_queryset(_request())

    @parameterized.expand(AUTORESEARCH_INLINES)
    def test_inline_queryset_does_not_need_team_context(
        self, _name: str, parent_model: type[Model], inline: type[admin.options.InlineModelAdmin]
    ) -> None:
        inline(parent_model, admin.site).get_queryset(_request())


class TestAdminWriteSurfaces(SimpleTestCase):
    def test_pipeline_team_is_locked_once_the_row_exists(self) -> None:
        model_admin = admin.site._registry[AutoresearchPipeline]
        assert "team" not in model_admin.get_readonly_fields(_request())
        # Children copy team at write time, so a later move would strand their history.
        assert "team" in model_admin.get_readonly_fields(_request(), obj=AutoresearchPipeline())

    def test_iterations_cannot_be_written_or_deleted_from_admin(self) -> None:
        model_admin = admin.site._registry[AutoresearchIteration]
        assert not model_admin.has_add_permission(_request())
        assert not model_admin.has_change_permission(_request())
        assert not model_admin.has_delete_permission(_request())
