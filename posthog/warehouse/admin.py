from django.contrib import admin
from posthog.warehouse.models import WarehouseCluster, WarehouseNode


class WarehouseNodeInline(admin.TabularInline):
    extra = 0
    model = WarehouseNode
    # readonly_fields = (joined_at", "updated_at")
    # autocomplete_fields = ("user", "organization")


@admin.register(WarehouseCluster)
class ClusterAdmin(admin.ModelAdmin):
    search_fields = ("organization__name", "name")
    ordering = ("-created_at",)
    inlines = [WarehouseNodeInline]
