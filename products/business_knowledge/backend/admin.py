from django.contrib import admin

from .models import KnowledgeChunk, KnowledgeDocument, KnowledgeSource


@admin.register(KnowledgeSource)
class KnowledgeSourceAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "team", "source_type", "status", "created_at")
    list_filter = ("source_type", "status", "created_at")
    search_fields = ("id", "name", "team__name")
    # Heavy FK to Team — use raw_id to avoid loading every team on change pages.
    raw_id_fields = ("team", "created_by")
    readonly_fields = ("id", "created_at", "updated_at")
    ordering = ("-created_at",)
    show_full_result_count = False


@admin.register(KnowledgeDocument)
class KnowledgeDocumentAdmin(admin.ModelAdmin):
    list_display = ("id", "source", "title", "team", "created_at")
    list_filter = ("created_at",)
    search_fields = ("id", "title", "stable_id", "source__name")
    raw_id_fields = ("team", "source")
    readonly_fields = ("id", "stable_id", "created_at", "updated_at")
    ordering = ("-created_at",)
    show_full_result_count = False


@admin.register(KnowledgeChunk)
class KnowledgeChunkAdmin(admin.ModelAdmin):
    list_display = ("id", "document", "heading_path", "ordinal", "char_count", "team")
    search_fields = ("id", "document__title", "heading_path")
    raw_id_fields = ("team", "source", "document")
    readonly_fields = ("id", "created_at")
    ordering = ("document_id", "ordinal")
    show_full_result_count = False
