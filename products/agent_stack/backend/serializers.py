"""DRF serializers for agent_stack."""

from __future__ import annotations

from rest_framework import serializers

from .models import AgentApplication, AgentApplicationRevision, AgentApplicationSession

REDACTED_VALUE = "********"


def redact_env(env_content: str | None) -> str:
    """Render a `.env` blob with every value replaced by `REDACTED_VALUE`, one
    `KEY=********` line per declared key. Suitable for UI display in a textarea
    or monospace block; preserves the original key order.
    """
    if not env_content:
        return ""
    lines: list[str] = []
    for raw_line in env_content.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key = stripped.split("=", 1)[0].strip()
        if key:
            lines.append(f"{key}={REDACTED_VALUE}")
    return "\n".join(lines)


# --- Output serializers ---


class AgentApplicationSerializer(serializers.ModelSerializer):
    slug = serializers.RegexField(
        regex=r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$",
        max_length=63,
        help_text=(
            "Subdomain prefix for the application. Globally unique across all teams. "
            "Lowercase letters, digits, and hyphens only; must start and end with a letter or digit."
        ),
    )
    has_env = serializers.SerializerMethodField(
        help_text="True if an encrypted env is set. Plaintext is never returned.",
    )
    env_redacted = serializers.SerializerMethodField(
        help_text=(
            "The application's `.env` rendered as text with every value replaced by "
            "asterisks (`KEY=********`). Suitable for showing in a textarea so the user "
            "can confirm which keys are set. Empty string when no env is configured."
        ),
    )

    class Meta:
        model = AgentApplication
        fields = [
            "id",
            "team",
            "name",
            "slug",
            "description",
            "has_env",
            "env_redacted",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "team",
            "has_env",
            "env_redacted",
            "created_by",
            "created_at",
            "updated_at",
        ]
        extra_kwargs = {
            "name": {"help_text": "Human-readable display name for the application."},
            "description": {"help_text": "Optional free-text description shown in the management UI."},
        }

    def get_has_env(self, obj: AgentApplication) -> bool:
        return bool(obj.encrypted_env)

    def get_env_redacted(self, obj: AgentApplication) -> str:
        return redact_env(obj.encrypted_env)

    def validate_slug(self, value: str) -> str:
        qs = AgentApplication.objects.filter(slug=value, deleted=False)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(f"slug '{value}' is already taken")
        return value


class AgentApplicationRevisionSerializer(serializers.ModelSerializer):
    class Meta:
        model = AgentApplicationRevision
        fields = [
            "id",
            "team",
            "application",
            "state",
            "deployment_status",
            "bundle_size",
            "bundle_sha256",
            "top_level_config",
            "parsed_manifest",
            "validation_report",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields  # Revisions are immutable via the public API.


class AgentApplicationSessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = AgentApplicationSession
        fields = [
            "id",
            "team",
            "application",
            "revision",
            "state",
            "queue_job_id",
            "parent_run_id",
            "trigger_type",
            "trigger_payload",
            "input",
            "output",
            "error",
            "runtime_instance",
            "created_at",
            "started_at",
            "last_heartbeat_at",
            "completed_at",
        ]
        read_only_fields = fields


# --- Input serializers for custom actions ---


class StartDeployRequestSerializer(serializers.Serializer):
    bundle_sha256 = serializers.RegexField(
        regex=r"^[0-9a-f]{64}$",
        help_text="SHA-256 of the bundle the CLI is about to upload, lowercase hex (64 chars).",
    )
    bundle_size = serializers.IntegerField(
        min_value=1,
        help_text="Bundle size in bytes. The presigned upload is bound to this exact size.",
    )
    top_level_config = serializers.JSONField(
        help_text=(
            "Parsed contents of `.ass.yaml`. Validated synchronously at deploy start; "
            "bundle-level checks are deferred to the async validator when it lands."
        ),
    )


class StartDeployResponseSerializer(serializers.Serializer):
    revision_id = serializers.UUIDField(help_text="The newly-created revision in state=pending_upload.")
    upload_url = serializers.CharField(help_text="Presigned S3 POST URL the CLI uploads the bundle to.")
    upload_fields = serializers.DictField(
        child=serializers.CharField(),
        help_text="Form fields the CLI must include in the multipart POST.",
    )
    expires_at = serializers.DateTimeField(help_text="When the presigned URL stops being valid.")
    max_size = serializers.IntegerField(help_text="Exact size in bytes the upload must be.")
    required_sha256 = serializers.CharField(help_text="SHA-256 the uploaded bundle must hash to.")


class CompleteUploadRequestSerializer(serializers.Serializer):
    revision_id = serializers.UUIDField(
        help_text="ID of the revision returned from start_deploy whose bundle has been uploaded.",
    )


class PromoteRevisionRequestSerializer(serializers.Serializer):
    revision_id = serializers.UUIDField(
        help_text=(
            "ID of the revision to promote. Must be state=ready. Any prior live revision "
            "on this application is atomically demoted to deployment_status=disabled."
        ),
    )


class PreviewRevisionRequestSerializer(serializers.Serializer):
    revision_id = serializers.UUIDField(
        help_text=(
            "ID of the revision to mark as preview. Must be state=ready. Multiple preview "
            "revisions can coexist; no siblings are demoted."
        ),
    )


class DisableRevisionRequestSerializer(serializers.Serializer):
    revision_id = serializers.UUIDField(
        help_text=(
            "ID of the revision to set deployment_status=disabled. Allowed from any state — "
            "use this to take a broken live or preview revision out of traffic."
        ),
    )


class UpdateEnvRequestSerializer(serializers.Serializer):
    env = serializers.CharField(
        trim_whitespace=False,
        allow_blank=True,
        style={"base_template": "textarea.html"},
        help_text=(
            "Raw `.env` contents to encrypt and store. Replaces the entire existing env. "
            "Plaintext never leaves the server after creation — the agent-runner decrypts in-process."
        ),
    )
