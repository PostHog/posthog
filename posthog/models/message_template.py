from django.db import models

from posthog.models.utils import UUIDModel


class MessageTemplateType(models.TextChoices):
    EMAIL = "email", "Email"


class MessageTemplate(UUIDModel):
    class Meta:
        indexes = [
            models.Index(fields=["type", "team"]),
        ]

    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    name = models.CharField(max_length=400)
    description = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, blank=True)
    created_by = models.ForeignKey("User", on_delete=models.SET_NULL, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted = models.BooleanField(default=False)
    type = models.CharField(max_length=24, choices=MessageTemplateType.choices)

    # JSON blob containing the message content and metadata
    # Example content structure using the Unlayer email builder schema:
    #   "email": {
    #     "value": {
    #       "to": "{person.properties.email}",
    #       "from": "info@posthog.com",
    #       "body": "Hi there {person.properties.first_name} {person.properties.last_name}. Thanks for signing up!",
    #       "html": "<!DOCTYPE html PUBLIC ...",
    #       "subject": "Hello {person.properties.first_name}!",
    #       "design": {
    #         "body": {
    #           "id": "TlJ2GekAva",
    #           "rows": [ ... ],
    #           "values": { ... },
    #           "footers": [],
    #           "headers": []
    #         },
    #         "counters": {
    #           "u_row": 1,
    #           "u_column": 1,
    #           "u_content_text": 1,
    #           "u_content_button": 1
    #         },
    #         "schemaVersion": 17
    #       }
    #     }
    #   }
    content = models.JSONField()

    def __str__(self):
        return f"{self.name} ({self.type})"
