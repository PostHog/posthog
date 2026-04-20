from django import forms
from django.contrib import admin

from posthog.models.batch_imports import BatchImport


class BatchImportAdminForm(forms.ModelForm):
    sink_type = forms.ChoiceField(
        choices=[("capture", "Capture"), ("kafka", "Kafka")],
        required=False,
        help_text="Capture sends events via HTTP; Kafka writes directly to Kafka.",
    )
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
            if sink.get("type"):
                self.fields["sink_type"].initial = sink["type"]
            if sink.get("send_rate"):
                self.fields["send_rate"].initial = sink["send_rate"]

    def save(self, commit=True):
        instance = super().save(commit=False)

        sink_type = self.cleaned_data.get("sink_type")
        send_rate = self.cleaned_data.get("send_rate")

        if sink_type:
            if not instance.import_config:
                instance.import_config = {}
            existing_sink = instance.import_config.get("sink", {})
            sink = {
                "type": sink_type,
                "send_rate": send_rate if send_rate is not None else existing_sink.get("send_rate", 1000),
            }
            if sink_type == "kafka":
                sink["topic"] = existing_sink.get("topic", "historical")
                sink["transaction_timeout_seconds"] = existing_sink.get("transaction_timeout_seconds", 60)

            instance.import_config["sink"] = sink

        if commit:
            instance.save()
        return instance


class BatchImportAdmin(admin.ModelAdmin):
    form = BatchImportAdminForm
    list_display = ("id", "team", "status", "created_by_id", "created_at", "get_sink_type", "get_send_rate")
    list_filter = ("status", "created_at")
    search_fields = ("id", "status_message", "team__name")
    readonly_fields = ("id", "created_at", "updated_at", "state", "import_config")
    autocomplete_fields = ("team",)
    fieldsets = (
        (None, {"fields": ("team", "created_by_id", "status", "status_message")}),
        (
            "Sink Configuration",
            {
                "fields": ("sink_type", "send_rate"),
                "description": "Configure the sink type and send rate for this batch import",
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

    @admin.display(description="Sink Type")
    def get_sink_type(self, obj):
        """Extract sink from import_config.sink"""
        if not obj.import_config:
            return None
        sink = obj.import_config.get("sink", {})
        return sink.get("type", "N/A")

    @admin.display(description="Send Rate")
    def get_send_rate(self, obj):
        """Extract send_rate from import_config.sink"""
        if not obj.import_config:
            return None
        sink = obj.import_config.get("sink", {})
        return sink.get("send_rate", "N/A")
