from typing import cast

from django import forms
from django.contrib import admin
from django.contrib.admin.widgets import ForeignKeyRawIdWidget
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import models
from django.http import HttpRequest
from django.urls import NoReverseMatch, reverse
from django.utils.text import Truncator

from posthog.models.scoping import team_scope
from posthog.models.scoping.manager import TeamScopedManager

from products.data_quality.backend.facade.models import DataQualityCheck, DataQualitySuiteRun

RAW_ID_LABEL_WORD_LIMIT = 14


class _UnscopedForeignKeyRawIdWidget(ForeignKeyRawIdWidget):
    # nosemgrep: tuple-return-prefer-dataclass -- Django's raw-ID widget requires a (label, URL) tuple.
    def label_and_url_for_value(self, value: object) -> tuple[str, str]:
        manager = cast(TeamScopedManager, self.rel.model._default_manager)
        try:
            related_object = manager.unscoped().using(self.db).get(**{self.rel.get_related_field().name: value})
        except (ValueError, ObjectDoesNotExist, ValidationError):
            return "", ""

        options = related_object._meta
        try:
            url = reverse(
                f"{self.admin_site.name}:{options.app_label}_{options.model_name}_change", args=[related_object.pk]
            )
        except NoReverseMatch:
            url = ""
        return Truncator(related_object).words(RAW_ID_LABEL_WORD_LIMIT), url


class _DataQualityAdminForm(forms.ModelForm):
    def _post_clean(self) -> None:
        team = self.cleaned_data.get("team")
        if team is None:
            return
        with team_scope(team.id):
            super()._post_clean()  # type: ignore[misc]


# nosemgrep: admin-modeladmin-needs-register-decorator -- Shared base; concrete admins below are registered.
class _DataQualityAdmin(admin.ModelAdmin):
    form = _DataQualityAdminForm

    def save_model(
        self,
        request: HttpRequest,
        obj: DataQualityCheck | DataQualitySuiteRun,
        form: forms.ModelForm,
        change: bool,
    ) -> None:
        with team_scope(obj.team_id):
            super().save_model(request, obj, form, change)

    def get_queryset(self, request: HttpRequest) -> models.QuerySet:
        queryset = cast(TeamScopedManager, self.model._default_manager).unscoped()
        ordering = self.get_ordering(request)
        return queryset.order_by(*ordering) if ordering else queryset

    def formfield_for_foreignkey(
        self, db_field: models.ForeignKey, request: HttpRequest, **kwargs: object
    ) -> forms.ModelChoiceField | None:
        manager = db_field.remote_field.model._default_manager
        if not isinstance(manager, TeamScopedManager):
            return super().formfield_for_foreignkey(db_field, request, **kwargs)

        database = cast(str | None, kwargs.pop("using", None))
        kwargs.setdefault("queryset", manager.unscoped().using(database))
        kwargs.setdefault(
            "widget", _UnscopedForeignKeyRawIdWidget(db_field.remote_field, self.admin_site, using=database)
        )
        return cast(
            forms.ModelChoiceField | None,
            models.Field.formfield(
                db_field,
                form_class=forms.ModelChoiceField,
                choices_form_class=cast(type[forms.ChoiceField] | None, kwargs.pop("choices_form_class", None)),
                to_field_name=db_field.remote_field.field_name,
                limit_choices_to=db_field.remote_field.limit_choices_to,
                blank=db_field.blank,
                **kwargs,
            ),
        )


@admin.register(DataQualityCheck)
class DataQualityCheckAdmin(_DataQualityAdmin):
    list_display = ("id", "check_type", "subject_name", "column_name", "severity", "enabled", "last_status")
    list_filter = ("check_type", "severity", "enabled", "subject_type", "subject_status")
    search_fields = ("id", "name", "subject_name", "team__id")
    raw_id_fields = ("team", "created_by", "definition_author", "owner", "saved_query", "table", "metric")
    readonly_fields = ("id", "fingerprint", "created_at", "updated_at", "last_run_at", "last_status")


@admin.register(DataQualitySuiteRun)
class DataQualitySuiteRunAdmin(_DataQualityAdmin):
    list_display = ("id", "trigger", "status", "checks_passed", "checks_failed", "checks_errored", "created_at")
    list_filter = ("trigger", "status")
    search_fields = ("id", "workflow_id", "team__id")
    raw_id_fields = ("team", "created_by")
    readonly_fields = ("id", "created_at", "updated_at", "started_at", "finished_at")
