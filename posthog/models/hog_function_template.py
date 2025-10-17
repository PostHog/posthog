import json
import hashlib
from typing import Optional

from django.db import models

import structlog

from posthog.models.utils import UUIDTModel

logger = structlog.get_logger(__name__)


class HogFunctionTemplate(UUIDTModel):
    """
    Django model for storing HogFunction templates in the database.
    This model replaces the in-memory storage of templates and enables sha versioning,
    efficient storage, and easier updates for HogFunction templates.
    """

    # Core Template Information
    template_id = models.CharField(max_length=255, db_index=True)
    sha = models.CharField(max_length=100, db_index=True)
    name = models.CharField(max_length=400)
    description = models.TextField(blank=True, null=True)

    # Core Template Content
    code = models.TextField()
    code_language = models.CharField(max_length=20, default="hog")  # "hog" or "javascript"
    inputs_schema = models.JSONField()
    bytecode = models.JSONField(null=True, blank=True)

    # Template Type and Status
    type = models.CharField(max_length=50)
    status = models.CharField(
        max_length=20,
        default="alpha",
    )

    # Template Classification and Features
    category = models.JSONField(default=list)
    # DEPRECATED: This was an idea that is no longer used
    kind = models.CharField(max_length=50, blank=True, null=True)
    free = models.BooleanField(default=False)
    icon_url = models.CharField(blank=True, null=True)

    # Additional Template Configuration
    filters = models.JSONField(blank=True, null=True)
    masking = models.JSONField(blank=True, null=True)

    # Template Relationships
    mapping_templates = models.JSONField(blank=True, null=True)

    # DEPRECATED: Templates only have mapping templates - to be removed in the future
    mappings = models.JSONField(blank=True, null=True)

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("template_id", "sha")
        indexes = [
            models.Index(fields=["template_id", "sha"]),
            models.Index(fields=["type", "status"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["template_id", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.template_id} sha:{self.sha})"

    def _generate_sha_from_content(self) -> str:
        """
        Generates a sha hash from template content for content-based versioning.
        """

        code = self.code.strip()

        template_dict = {
            "id": self.template_id,
            "code": code,
            "code_language": self.code_language,
            "inputs_schema": self.inputs_schema,
            "status": self.status,
            "mapping_templates": self.mapping_templates,
            "filters": self.filters,
            "icon_url": self.icon_url,
            "masking": self.masking,
        }

        # Create a SHA256 hash of the content
        content_for_hash = json.dumps(template_dict, sort_keys=True)
        content_hash = hashlib.sha256(content_for_hash.encode("utf-8")).hexdigest()
        # Use first 8 characters as the sha hash
        return content_hash[:8]

    @classmethod
    def get_template(cls, template_id: str, sha: Optional[str] = None) -> Optional["HogFunctionTemplate"]:
        """
        Gets a template by ID and optionally sha.
        Args:
            template_id: The ID of the template to get
            sha: The sha to get, or None for the latest sha
        Returns:
            The template instance, or None if no template was found
        """
        try:
            if sha:
                # Get the specific sha
                return cls.objects.filter(
                    template_id=template_id,
                    sha=sha,
                ).first()
            else:
                # Get the latest sha by created_at timestamp
                # We allow all templates to be loaded, even deprecated ones as they might still be used by customers - they just aren't listable in the UI
                return cls.objects.filter(template_id=template_id).order_by("-created_at").first()
        except Exception as e:
            logger.error(
                "Failed to get template from database",
                template_id=template_id,
                sha=sha,
                error=str(e),
                exc_info=True,
            )
            return None

    def compile_bytecode(self):
        """
        Compiles the Hog code_language code to bytecode and stores it in the bytecode field.
        This should be called after changing the code field.
        """
        if self.code_language != "hog":
            self.bytecode = None
            return
        try:
            from posthog.cdp.validation import compile_hog

            # Compile the hog code_language to bytecode and store it in the database field
            self.bytecode = compile_hog(self.code, self.type)
        except Exception as e:
            logger.error(
                "Failed to compile template bytecode",
                template_id=self.template_id,
                sha=self.sha,
                error=str(e),
                exc_info=True,
            )
            self.bytecode = None

    def save(self, *args, **kwargs):
        """
        Saves the template to the database.
        """
        self.compile_bytecode()
        self.sha = self._generate_sha_from_content()
        super().save(*args, **kwargs)
