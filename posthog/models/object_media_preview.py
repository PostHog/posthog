from django.core.exceptions import ValidationError
from django.db import models

from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel


class ObjectMediaPreview(UUIDModel, CreatedMetaFields, UpdatedMetaFields):
    """
    Links media to objects like event definitions, property definitions, etc.
    Supports both user-uploaded screenshots and exported assets from session replays.
    """

    team = models.ForeignKey("Team", on_delete=models.CASCADE)

    # Media - exactly one must be set
    uploaded_media = models.ForeignKey(
        "UploadedMedia",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="object_previews",
    )
    exported_asset = models.ForeignKey(
        "ExportedAsset",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="object_previews",
    )

    # Object - exactly one must be set
    # Previews for other objects could be added here later (e.g. property_definition, feature_flag)
    # When adding, update the constraint below to ensure exactly one is set
    event_definition = models.ForeignKey(
        "EventDefinition",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="media_previews",
    )

    # Metadata - URL where screenshot was taken, recording_id, feature flag values, etc.
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["team", "event_definition"]),
        ]
        constraints = [
            models.CheckConstraint(
                check=(
                    models.Q(uploaded_media__isnull=False, exported_asset__isnull=True)
                    | models.Q(uploaded_media__isnull=True, exported_asset__isnull=False)
                ),
                name="exactly_one_media",
            ),
            models.CheckConstraint(
                check=models.Q(event_definition__isnull=False),
                name="exactly_one_object",
            ),
        ]

    def clean(self):
        super().clean()

        media_count = sum(
            [
                self.uploaded_media_id is not None,
                self.exported_asset_id is not None,
            ]
        )
        if media_count != 1:
            raise ValidationError("Exactly one of uploaded_media or exported_asset must be set")

        if not self.event_definition_id:
            raise ValidationError("event_definition must be set")

        # Validate team consistency
        if self.uploaded_media and self.uploaded_media.team_id != self.team_id:
            raise ValidationError("Uploaded media team must match preview team")
        if self.exported_asset and self.exported_asset.team_id != self.team_id:
            raise ValidationError("Exported asset team must match preview team")
        if self.event_definition and self.event_definition.team_id != self.team_id:
            raise ValidationError("Event definition team must match preview team")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def related_object(self):
        """Return the actual related object"""
        return self.event_definition

    @property
    def media_url(self) -> str:
        """Get the URL to access the media"""
        if self.uploaded_media:
            return self.uploaded_media.get_absolute_url()
        elif self.exported_asset:
            return self.exported_asset.get_public_content_url()
        return ""

    def __str__(self) -> str:
        object_ref = f"event_definition:{self.event_definition_id}"
        if self.uploaded_media_id:
            media_ref = f"uploaded_media:{self.uploaded_media_id}"
        else:
            media_ref = f"exported_asset:{self.exported_asset_id}"
        return f"{object_ref} -> {media_ref}"
