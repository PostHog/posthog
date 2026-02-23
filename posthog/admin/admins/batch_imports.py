from django import forms
from django.contrib import admin

from posthog.models.batch_imports import BatchImport


class BatchImportAdminForm(forms.ModelForm):
    send_rate = forms.IntegerField(
        required=False,
        help_text="Events per second to send (e.g., 1000). Leave empty to keep current value.",
        widget=forms.NumberInput(attrs={"placeholder": "e.g., 1000"}),
    )

    class Meta:
        model = BatchImport
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.import_config:
            sink = self.instance.import_config.get("sink", {})
            current_send_rate = sink.get("send_rate")
            if current_send_rate:
                self.fields["send_rate"].initial = current_send_rate

    def save(self, commit=True):
        instance = super().save(commit=False)

        send_rate = self.cleaned_data.get("send_rate")
        if send_rate is not None:
            if not instance.import_config:
                instance.import_config = {}
            if "sink" not in instance.import_config:
                instance.import_config["sink"] = {}
            instance.import_config["sink"]["send_rate"] = send_rate

        if commit:
            instance.save()
        return instance


class BatchImportAdmin(admin.ModelAdmin):
    form = BatchImportAdminForm
    list_display = ("id", "team", "status", "created_by_id", "created_at", "get_send_rate")
    list_filter = ("status", "created_at")
    search_fields = ("id", "status_message", "team__name")
    readonly_fields = ("id", "created_at", "updated_at", "state", "import_config")
    autocomplete_fields = ("team",)
    fieldsets = (
        (None, {"fields": ("team", "created_by_id", "status", "status_message")}),
        (
            "Rate Configuration",
            {
                "fields": ("send_rate",),
                "description": "Configure the send rate for this batch import",
            },
        ),
        (
            "Import Configuration",
            {
                "fields": ("import_config",),
                "description": "Full JSON configuration (read-only)",
            },
        ),
        ("Metadata", {"fields": ("id", "created_at", "updated_at", "state")}),
    )

    @admin.display(description="Send Rate")
    def get_send_rate(self, obj):
        """Extract send_rate from import_config.sink"""
        if not obj.import_config:
            return None
        sink = obj.import_config.get("sink", {})
        return sink.get("send_rate", "N/A")
