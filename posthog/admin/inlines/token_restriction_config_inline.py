from django.contrib import admin
from django.forms import ModelForm
from django.utils.html import format_html
from posthog.models import TokenRestrictionConfig


class TokenRestrictionConfigForm(ModelForm):
    class Meta:
        model = TokenRestrictionConfig
        fields = [
            "tokens_to_skip_person_processing",
            "tokens_to_drop_events_from_ingestion",
            "tokens_to_force_overflow_from_ingestion",
        ]
        help_texts = {
            "tokens_to_skip_person_processing": "List of token or token:distinct_id to skip person processing for",
            "tokens_to_drop_events_from_ingestion": "List of token or token:distinct_id to drop events from ingestion for",
            "tokens_to_force_overflow_from_ingestion": "List of token or token:distinct_id to force overflow from ingestion for",
        }


class TokenRestrictionConfigInline(admin.StackedInline):
    model = TokenRestrictionConfig
    form = TokenRestrictionConfigForm
    verbose_name = "Token Restrictions"
    verbose_name_plural = "Token Restrictions"
    can_delete = False

    fieldsets = (
        (
            None,
            {
                "fields": (
                    "tokens_to_skip_person_processing",
                    "tokens_to_drop_events_from_ingestion",
                    "tokens_to_force_overflow_from_ingestion",
                ),
                "description": format_html(
                    '<div class="help">'
                    "Configure token restrictions for this team.<br>"
                    "- <strong>Skip person processing</strong>: Events with these token/token:distinct_id combo will not create or update person records<br>"
                    "- <strong>Drop events</strong>: Events with these token/token:distinct_id combo will be dropped completely<br>"
                    "- <strong>Force overflow</strong>: Events with these token/token:distinct_id combo will be sent to overflow processing"
                    "</div>"
                ),
            },
        ),
    )
