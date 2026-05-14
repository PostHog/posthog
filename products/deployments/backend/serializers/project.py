"""Serializer for DeploymentProject.

`github_integration` is the id of a `posthog.Integration` row with `kind="github"`
that belongs to the same team. The serializer validates ownership and kind at
write time. Secrets (the access token) never travel through the serializer —
they live on the Integration row and are resolved at deploy time.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from posthog.models.integration import Integration

from ..models import DeploymentProject


class DeploymentProjectSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(read_only=True, help_text="Unique identifier for the deployment project.")
    name = serializers.CharField(max_length=200, help_text="Human-readable project name shown in the UI.")
    slug = serializers.SlugField(
        max_length=80,
        help_text=(
            "URL-safe handle. Combined with the team id to form the Cloudflare project name; "
            "the actual subdomain comes from Cloudflare and is returned in the read-only "
            "`subdomain` field. Must be unique per team."
        ),
    )
    repo_url = serializers.URLField(
        max_length=1024,
        help_text="HTTPS URL of the source repository this project deploys from.",
    )
    default_branch = serializers.CharField(
        max_length=255,
        required=False,
        default="main",
        help_text="Branch the project deploys from when no commit SHA is pinned. Defaults to `main`.",
    )
    github_integration = serializers.IntegerField(
        source="github_integration_id",
        required=False,
        allow_null=True,
        help_text=(
            "ID of the `posthog.Integration` row (kind=github) the project uses to read this "
            "repository. Must belong to the same team. The actual access token lives on the "
            "Integration row and is never exposed through this serializer."
        ),
    )

    build_command = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text=(
            "Optional shell command run inside the build container. Null = the build worker "
            "infers it from `framework` (or auto-detection if framework is also null)."
        ),
    )
    output_dir = serializers.CharField(
        max_length=255,
        required=False,
        default="dist",
        help_text="Directory containing the built static site, relative to the repository root.",
    )
    framework = serializers.CharField(
        max_length=50,
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Optional framework hint (e.g. `nextjs`, `vite`, `astro`). Null = auto-detect.",
    )
    inject_posthog_snippet = serializers.BooleanField(
        required=False,
        default=False,
        help_text=(
            "If true, the build injects a PostHog snippet into every HTML file that registers "
            "`release = deployment_id` as a super-property — runtime exceptions are then linked "
            "back to the deployment that introduced them."
        ),
    )

    cloudflare_project_name = serializers.CharField(
        read_only=True,
        help_text="Cloudflare Pages project name, assigned during provisioning.",
    )
    subdomain = serializers.CharField(
        read_only=True,
        help_text="Public subdomain at which deployments of this project serve.",
    )
    cloudflare_ready_at = serializers.DateTimeField(
        read_only=True,
        allow_null=True,
        help_text="Timestamp when the Cloudflare project was fully provisioned and ready to receive deploys.",
    )

    current_deployment: serializers.PrimaryKeyRelatedField = serializers.PrimaryKeyRelatedField(  # ty: ignore[invalid-assignment]
        read_only=True,
        allow_null=True,
        help_text="The deployment currently serving traffic for this project. Null if no deployment has ever succeeded.",
    )

    is_ready_to_deploy = serializers.SerializerMethodField(
        help_text=(
            "True when the project has both a provisioned Cloudflare backend and a configured "
            "GitHub credential — meaning a deploy can be triggered right now."
        ),
    )

    created_at = serializers.DateTimeField(
        read_only=True,
        help_text="Timestamp when the project was created.",
    )
    updated_at = serializers.DateTimeField(
        read_only=True,
        help_text="Timestamp when the project was last modified.",
    )

    class Meta:
        model = DeploymentProject
        fields = [
            "id",
            "name",
            "slug",
            "repo_url",
            "default_branch",
            "github_integration",
            "build_command",
            "output_dir",
            "framework",
            "inject_posthog_snippet",
            "cloudflare_project_name",
            "subdomain",
            "cloudflare_ready_at",
            "current_deployment",
            "is_ready_to_deploy",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "cloudflare_project_name",
            "subdomain",
            "cloudflare_ready_at",
            "current_deployment",
            "is_ready_to_deploy",
            "created_at",
            "updated_at",
        ]

    @extend_schema_field(serializers.BooleanField())
    def get_is_ready_to_deploy(self, obj: DeploymentProject) -> bool:
        return obj.cloudflare_ready_at is not None and obj.github_integration_id is not None

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        # The field uses `source="github_integration_id"`, so the int lands under that key.
        integration_id = attrs.get("github_integration_id")
        if integration_id is None:
            return attrs
        team = self.context["get_team"]()
        if not Integration.objects.filter(id=integration_id, team_id=team.id, kind="github").exists():
            raise serializers.ValidationError(
                {"github_integration": "Integration not found or is not a GitHub integration for this team."}
            )
        return attrs

    def validate_repo_url(self, value: str) -> str:
        # v1 deploys from github.com only. Without this check the field
        # would accept any URL — including http://169.254.169.254/... or
        # other internal/link-local hosts the build worker / GitHub
        # adapter would then connect to (SSRF). Restricting scheme +
        # host is the smallest fix that closes that vector.
        parsed = urlparse(value)
        if parsed.scheme != "https":
            raise serializers.ValidationError("repo_url must use HTTPS.")
        if (parsed.hostname or "").lower() != "github.com":
            raise serializers.ValidationError("repo_url must point to github.com.")
        return value
