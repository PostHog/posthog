from django.contrib import admin

from products.data_quality.backend.facade.models import DataQualityCheck, DataQualitySuiteRun


@admin.register(DataQualityCheck)
class DataQualityCheckAdmin(admin.ModelAdmin):
    list_display = ("id", "check_type", "subject_name", "column_name", "severity", "enabled", "last_status")
    list_filter = ("check_type", "severity", "enabled", "subject_type", "subject_status")
    search_fields = ("id", "name", "subject_name", "team__id")
    raw_id_fields = ("team", "created_by", "definition_author", "owner", "saved_query", "table")
    readonly_fields = ("id", "fingerprint", "created_at", "updated_at", "last_run_at", "last_status")


@admin.register(DataQualitySuiteRun)
class DataQualitySuiteRunAdmin(admin.ModelAdmin):
    list_display = ("id", "trigger", "status", "checks_passed", "checks_failed", "checks_errored", "created_at")
    list_filter = ("trigger", "status")
    search_fields = ("id", "workflow_id", "team__id")
    raw_id_fields = ("team", "created_by")
    readonly_fields = ("id", "created_at", "updated_at", "started_at", "finished_at")
