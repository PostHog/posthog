from django.db import models
from typing import Optional, cast
import hashlib
import structlog
import dataclasses

from posthog.models.utils import UUIDModel
from posthog.cdp.templates.hog_function_template import (
    HogFunctionTemplateType,
    HogFunctionTemplateKind,
    HogFunctionTemplate as HogFunctionTemplateDTO,
    HogFunctionMapping,
    HogFunctionMappingTemplate,
    HogFunctionSubTemplate,
)

logger = structlog.get_logger(__name__)


class HogFunctionTemplate(UUIDModel):
    """
    Django model for storing HogFunction templates in the database.
    This model replaces the in-memory storage of templates and enables versioning,
    efficient storage, and easier updates for HogFunction templates.
    """

    # Core Template Information
    template_id = models.CharField(max_length=255, db_index=True)
    version = models.CharField(max_length=100, db_index=True)
    name = models.CharField(max_length=400)
    description = models.TextField(blank=True, null=True)

    # Core Template Content
    hog = models.TextField()
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
    kind = models.CharField(max_length=50, blank=True, null=True)
    free = models.BooleanField(default=False)
    icon_url = models.URLField(blank=True, null=True)

    # Additional Template Configuration
    filters = models.JSONField(blank=True, null=True)
    masking = models.JSONField(blank=True, null=True)

    # Template Relationships
    sub_templates = models.JSONField(blank=True, null=True)
    mappings = models.JSONField(blank=True, null=True)
    mapping_templates = models.JSONField(blank=True, null=True)

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("template_id", "version")
        indexes = [
            models.Index(fields=["template_id", "version"]),
            models.Index(fields=["type", "status"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["template_id", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.template_id} v{self.version})"

    @classmethod
    def generate_version_from_content(cls, content: str) -> str:
        """
        Generates a version hash from template content for content-based versioning.
        """
        # Create a SHA256 hash of the content
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        # Use first 8 characters as the version
        return content_hash[:8]

    @classmethod
    def get_template(cls, template_id: str, version: Optional[str] = None):
        """
        Gets a template by ID and optionally version.
        Args:
            template_id: The ID of the template to get
            version: The version to get, or None for the latest version
        Returns:
            The template instance, or None if no template was found
        """
        try:
            if version:
                # Get the specific version
                return cls.objects.filter(
                    template_id=template_id,
                    version=version,
                ).first()
            else:
                # Get the latest version by created_at timestamp
                # Only include active templates (not deprecated)
                return (
                    cls.objects.filter(template_id=template_id, status__not_in=["deprecated"])
                    .order_by("-created_at")
                    .first()
                )
        except Exception as e:
            logger.error(
                "Failed to get template from database",
                template_id=template_id,
                version=version,
                error=str(e),
                exc_info=True,
            )
            return None

    @classmethod
    def get_latest_templates(cls, template_type=None, include_deprecated=False):
        """
        Gets the latest version of each template, optionally filtered by type.
        This is more efficient than get_all_templates when you only need the latest version
        of each template.
        Args:
            template_type: Optional type to filter templates by
            include_deprecated: Whether to include deprecated templates
        Returns:
            A list of template instances, one per template_id
        """
        # Build the filter conditions
        filters = {}
        if template_type:
            filters["type"] = template_type

        if not include_deprecated:
            filters["status__in"] = ["alpha", "beta", "stable"]

        # First get the latest template_id and version pairs
        from django.db.models import Subquery, OuterRef, Max

        # Get the max created_at for each template_id
        latest_created_at = (
            cls.objects.filter(template_id=OuterRef("template_id"))
            .values("template_id")
            .annotate(max_created=Max("created_at"))
            .values("max_created")
        )

        # Query templates matching the max created_at for their template_id
        latest_templates = cls.objects.filter(**filters, created_at=Subquery(latest_created_at)).order_by("template_id")

        return latest_templates

    def to_dataclass(self) -> HogFunctionTemplateDTO:
        """
        Converts this database model to a HogFunctionTemplateDTO dataclass.
        This allows integration with existing code that expects the dataclass.
        Returns:
            A HogFunctionTemplateDTO instance
        """
        # Convert mappings from JSON to dataclasses if they exist
        mappings_list: list[HogFunctionMapping] = []
        if self.mappings:
            for mapping_dict in self.mappings:
                mappings_list.append(HogFunctionMapping(**mapping_dict))

        # Convert sub_templates from JSON to dataclasses if they exist
        sub_templates_list: list[HogFunctionSubTemplate] = []
        if self.sub_templates:
            for sub_template_dict in self.sub_templates:
                sub_templates_list.append(HogFunctionSubTemplate(**sub_template_dict))

        # Convert mapping_templates from JSON to dataclasses if they exist
        mapping_templates_list: list[HogFunctionMappingTemplate] = []
        if self.mapping_templates:
            for mapping_template_dict in self.mapping_templates:
                mapping_templates_list.append(HogFunctionMappingTemplate(**mapping_template_dict))

        # Create the dataclass
        return HogFunctionTemplateDTO(
            id=self.template_id,
            name=self.name,
            hog=self.hog,
            inputs_schema=self.inputs_schema,
            free=self.free,
            type=cast(HogFunctionTemplateType, self.type),
            status=self.status,
            category=self.category,
            description=self.description,
            kind=cast(HogFunctionTemplateKind, self.kind) if self.kind else None,
            filters=self.filters,
            masking=self.masking,
            icon_url=self.icon_url,
            sub_templates=sub_templates_list if sub_templates_list else None,
            mappings=mappings_list if mappings_list else None,
            mapping_templates=mapping_templates_list if mapping_templates_list else None,
        )

    def compile_bytecode(self):
        """
        Compiles the Hog source code to bytecode and stores it in the bytecode field.
        This should be called after changing the hog field.
        """
        try:
            from posthog.cdp.validation import compile_hog

            # Compile the hog source to bytecode and store it in the database field
            self.bytecode = compile_hog(self.hog, self.type)
        except Exception as e:
            logger.error(
                "Failed to compile template bytecode",
                template_id=self.template_id,
                version=self.version,
                error=str(e),
                exc_info=True,
            )
            self.bytecode = None

    @classmethod
    def create_from_dataclass(cls, dataclass_template):
        """
        Creates and saves a HogFunctionTemplate database model from a dataclass template.
        Version is always calculated based on content hash.
        Args:
            dataclass_template: The dataclass template to convert
        Returns:
            The saved database template instance
        """
        from posthog.cdp.templates.hog_function_template import HogFunctionTemplate as DataclassTemplate
        from posthog.cdp.validation import compile_hog
        import json

        # Verify the dataclass_template is the correct type
        if not isinstance(dataclass_template, DataclassTemplate):
            raise TypeError(f"Expected HogFunctionTemplate dataclass, got {type(dataclass_template)}")

        # Calculate version based on content hash
        template_dict = {
            "id": dataclass_template.id,
            "hog": dataclass_template.hog,
            "inputs_schema": dataclass_template.inputs_schema,
        }
        content_for_hash = json.dumps(template_dict, sort_keys=True)
        version = cls.generate_version_from_content(content_for_hash)

        # Convert collections to JSON
        mappings = None
        if dataclass_template.mappings:
            mappings = [dataclasses.asdict(mapping) for mapping in dataclass_template.mappings]

        sub_templates = None
        if dataclass_template.sub_templates:
            sub_templates = [dataclasses.asdict(template) for template in dataclass_template.sub_templates]

        mapping_templates = None
        if dataclass_template.mapping_templates:
            mapping_templates = [dataclasses.asdict(template) for template in dataclass_template.mapping_templates]

        # Compile bytecode
        try:
            bytecode = compile_hog(dataclass_template.hog, dataclass_template.type)
        except Exception as e:
            logger.error(
                "Failed to compile template bytecode during creation",
                template_id=dataclass_template.id,
                error=str(e),
                exc_info=True,
            )
            bytecode = None

        # Create and save the database template instance
        return cls.objects.create(
            template_id=dataclass_template.id,
            version=version,
            name=dataclass_template.name,
            description=dataclass_template.description,
            hog=dataclass_template.hog,
            inputs_schema=dataclass_template.inputs_schema,
            bytecode=bytecode,
            type=dataclass_template.type,
            status=dataclass_template.status,
            category=dataclass_template.category,
            kind=dataclass_template.kind,
            free=dataclass_template.free,
            icon_url=dataclass_template.icon_url,
            filters=dataclass_template.filters,
            masking=dataclass_template.masking,
            sub_templates=sub_templates,
            mappings=mappings,
            mapping_templates=mapping_templates,
        )
