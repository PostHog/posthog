"""Serializer for DeploymentProject.

`github_pat` is write-only — the EncryptedTextField stores a Fernet
ciphertext at rest, but we never return it (even encrypted) to API
clients. PATCH accepts it; GET responses omit it entirely.
"""

from __future__ import annotations

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from ..models import DeploymentProject


class DeploymentProjectSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(read_only=True, help_text="Unique identifier for the deployment project.")
    name = serializers.CharField(max_length=200, help_text="Human-readable project name shown in the UI.")
    slug = serializers.SlugField(
        max_length=80,
        help_text="URL-safe handle. Becomes the subdomain `{slug}.posthog-app.com`. Must be unique per team.",
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
    github_pat = serializers.CharField(
        max_length=500,
        write_only=True,
        required=False,
        allow_blank=False,
        allow_null=True,
        help_text=(
            "GitHub personal access token used to read the repository. Encrypted at rest. Never returned in responses."
        ),
    )

    build_command = serializers.CharField(
        required=False,
        default="pnpm install && pnpm build",
        help_text="Shell command run inside the build container. Defaults to `pnpm install && pnpm build`.",
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

    current_deployment = serializers.PrimaryKeyRelatedField(
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
            "github_pat",
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
        return obj.cloudflare_ready_at is not None and bool(obj.github_pat)
