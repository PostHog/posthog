"""Serializer for DeploymentProject.

Repository selection is keyed by ``github_integration_id`` + ``github_repo_id``.
``repo_url`` is derived from GitHub and exposed as read-only display metadata.
Secrets (the access token) never travel through the serializer — they live on
the Integration row and are resolved at deploy time.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from ..models import DeploymentProject


class RejectUnknownFieldsMixin(serializers.Serializer):
    def to_internal_value(self, data: Any) -> Any:
        if isinstance(data, Mapping):
            unknown_fields = set(data) - set(self.fields)
            if unknown_fields:
                raise serializers.ValidationError(dict.fromkeys(sorted(unknown_fields), "Unknown field."))
        return super().to_internal_value(data)


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
        read_only=True,
        help_text="HTTPS URL of the connected GitHub repository, resolved from the selected repository id.",
    )
    default_branch = serializers.CharField(
        max_length=255,
        required=False,
        help_text="Branch PostHog tracks for deployment updates. Defaults to the repository default branch.",
    )
    github_integration_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="Existing PostHog GitHub integration id used for repository access.",
    )
    github_repo_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="Stable GitHub repository identifier selected from the existing integration's repository list.",
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
            "github_integration_id",
            "github_repo_id",
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
            "repo_url",
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


class DeploymentProjectWriteSerializer(RejectUnknownFieldsMixin, serializers.ModelSerializer):
    name = serializers.CharField(max_length=200, help_text="Human-readable project name shown in the UI.")
    slug = serializers.SlugField(
        max_length=80,
        help_text=(
            "URL-safe handle. Combined with the team id to form the Cloudflare project name; "
            "the actual subdomain comes from Cloudflare and is returned in the read-only "
            "`subdomain` field. Must be unique per team."
        ),
    )
    default_branch = serializers.CharField(
        max_length=255,
        required=False,
        help_text="Branch PostHog tracks for deployment updates. Defaults to the repository default branch.",
    )
    github_integration_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="Existing PostHog GitHub integration id used for repository access.",
    )
    github_repo_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="Stable GitHub repository identifier selected from the existing integration's repository list.",
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

    class Meta:
        model = DeploymentProject
        fields = [
            "name",
            "slug",
            "default_branch",
            "github_integration_id",
            "github_repo_id",
            "build_command",
            "output_dir",
            "framework",
            "inject_posthog_snippet",
        ]


class DeploymentProjectCreateSerializer(RejectUnknownFieldsMixin, serializers.Serializer):
    name = serializers.CharField(max_length=200, help_text="Human-readable project name shown in the UI.")
    slug = serializers.SlugField(
        max_length=80,
        help_text="URL-safe handle. Becomes the subdomain `{slug}.posthog-app.com`. Must be unique per team.",
    )
    default_branch = serializers.CharField(
        max_length=255,
        required=False,
        help_text="Branch PostHog tracks for deployment updates. Defaults to the repository default branch.",
    )
    github_integration_id = serializers.IntegerField(
        help_text="Existing PostHog GitHub integration id used for repository access."
    )
    github_repo_id = serializers.IntegerField(
        help_text="Stable GitHub repository identifier selected from the existing integration's repository list."
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
