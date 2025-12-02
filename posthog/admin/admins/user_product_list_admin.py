from django import forms
from django.contrib import admin

from posthog.models.file_system.user_product_list import UserProductList
from posthog.products import Products


class UserProductListAdminForm(forms.ModelForm):
    class Meta:
        model = UserProductList
        fields = ["user", "team", "product_path", "reason", "reason_text", "enabled"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "product_path" in self.fields:
            product_paths = Products.get_product_paths()
            self.fields["product_path"].widget = forms.Select(
                choices=[("", "---------")] + [(path, path) for path in product_paths]
            )
        if "reason" in self.fields:
            self.fields["reason"].initial = UserProductList.Reason.SALES_LED
        if "enabled" in self.fields:
            self.fields["enabled"].initial = True
        if "reason_text" in self.fields:
            self.fields["reason_text"].required = False
            self.fields["reason_text"].widget.attrs["rows"] = 8
            self.fields["reason_text"].widget.attrs["placeholder"] = (
                "We default to displaying this message in the UI when adding a new product: \"We've added this product to your sidebar because we believe you'd benefit from it! Your TAM will reach out to help you learn more about it.\""
                "\nYou can override with a custom message here, make it personal!"
                "\n\nExample: Hey, it's Rafael. I believe you'll like using our new SQL Editor! I went ahead and gave you 1,000,000 free rows, Merry Christmas!"
            )


class UserProductListAdmin(admin.ModelAdmin):
    form = UserProductListAdminForm
    list_display = ("id", "user", "team", "product_path", "reason", "enabled", "created_at", "updated_at")
    list_display_links = ("id",)
    list_filter = (
        "reason",
        "product_path",
        "enabled",
        ("created_at", admin.DateFieldListFilter),
    )
    search_fields = ("product_path", "user__email", "team__name")
    ordering = ("-created_at",)
    list_select_related = ("user", "team")
    list_per_page = 50
    autocomplete_fields = ["user", "team"]

    fieldsets = [
        (
            None,
            {
                "fields": ["user", "team", "product_path"],
            },
        ),
        (
            "Status",
            {
                "fields": ["enabled", "reason", "reason_text"],
            },
        ),
    ]

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return ["id", "user", "team", "product_path", "reason", "enabled", "created_at", "updated_at"]
        return []

    def get_fieldsets(self, request, obj=None):
        if obj:
            return [
                (
                    None,
                    {
                        "fields": ["user", "team", "product_path"],
                    },
                ),
                (
                    "Status",
                    {
                        "fields": ["enabled", "reason", "reason_text"],
                    },
                ),
                (
                    "Timestamps",
                    {
                        "fields": ["created_at", "updated_at"],
                    },
                ),
            ]
        return self.fieldsets

    def has_add_permission(self, request):
        return True

    def has_change_permission(self, request, obj=None):
        if obj is None:
            return True
        if obj.reason == UserProductList.Reason.SALES_LED:
            return True
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        if not change:
            obj.reason = UserProductList.Reason.SALES_LED
            obj.enabled = True
        super().save_model(request, obj, form, change)
