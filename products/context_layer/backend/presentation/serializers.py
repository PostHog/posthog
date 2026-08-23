from rest_framework import serializers

from products.context_layer.backend.facade.api import PAGE_MAX_BYTES

# A bundle carries a handful of Markdown commits; anything bigger is not a wiki write-back.
COMMIT_BUNDLE_MAX_BYTES = 25_000_000


class ContextLayerStatusSerializer(serializers.Serializer):
    """Response shape for the wiki's current state."""

    head_sha = serializers.CharField(help_text="Commit sha of the wiki's current head.")


class WikiTreeSerializer(serializers.Serializer):
    """Response shape for the wiki's page listing."""

    head_sha = serializers.CharField(help_text="Commit sha of the wiki's current head.")
    paths = serializers.ListField(
        child=serializers.CharField(),
        help_text="Repo-relative path of every Markdown page at the current head.",
    )


class WikiPageSerializer(serializers.Serializer):
    """Response shape for one wiki page."""

    path = serializers.CharField(help_text="Repo-relative path of the page, for example `areas/analytics.md`.")
    content = serializers.CharField(allow_blank=True, help_text="The page's Markdown content.")
    head_sha = serializers.CharField(
        help_text="Commit sha the content was read at; pass back as `base_head` on writes."
    )


class WikiPageWriteSerializer(serializers.Serializer):
    """Request body for creating or replacing one wiki page."""

    path = serializers.CharField(
        max_length=512,
        help_text="Repo-relative Markdown path inside the wiki's structure, for example `channels/general.md`.",
    )
    content = serializers.CharField(
        allow_blank=True,
        trim_whitespace=False,
        max_length=PAGE_MAX_BYTES,
        help_text="The complete Markdown content for the page.",
    )
    base_head = serializers.CharField(
        required=False,
        allow_null=True,
        help_text=(
            "Optimistic-concurrency guard: the head sha the edit is based on. A moved head is rejected "
            "with 409 and the current head; omit to write unguarded."
        ),
    )


class CommitBundleSerializer(serializers.Serializer):
    """Request body for landing agent commits posted back as a git bundle."""

    bundle = serializers.FileField(
        help_text=(
            "A `git bundle` carrying the wiki's `main` ref, created in the agent's clone "
            "(for example `git bundle create out.bundle origin/main..main`)."
        )
    )

    def validate_bundle(self, value):  # noqa: ANN001, ANN201
        if value.size > COMMIT_BUNDLE_MAX_BYTES:
            raise serializers.ValidationError(f"Bundle exceeds the {COMMIT_BUNDLE_MAX_BYTES // 1_000_000} MB limit.")
        return value


class WikiExportSerializer(serializers.Serializer):
    """Response shape for a wiki bundle export."""

    url = serializers.CharField(help_text="Short-lived download URL for the wiki's current bundle.")
    head_sha = serializers.CharField(help_text="Commit sha of the bundle behind the URL.")


class HeadConflictSerializer(serializers.Serializer):
    """409 body when a guarded write was based on a stale head."""

    detail = serializers.CharField(help_text="What moved and what to do next.")
    current_head = serializers.CharField(help_text="The wiki's current head sha; re-read pages at this head and retry.")


class LintErrorSerializer(serializers.Serializer):
    """400 body when a write violates the wiki's structure rules."""

    detail = serializers.CharField(help_text="What was rejected.")
    # The response key is part of the API; DRF's Serializer.errors property only
    # matters for validation, which this response-shape serializer never does.
    errors = serializers.ListField(  # type: ignore[assignment]
        child=serializers.CharField(), help_text="One entry per structure violation found by the linter."
    )
