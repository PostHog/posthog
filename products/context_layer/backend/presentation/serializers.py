from rest_framework import serializers

from products.context_layer.backend.facade.api import DREAM_BRANCH_RE, PAGE_MAX_BYTES

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
    updated_at = serializers.DateTimeField(help_text="When this page was last changed in the wiki history.")


class WikiHealthFindingSerializer(serializers.Serializer):
    category = serializers.CharField(help_text="Stable category used to group this finding.")
    path = serializers.CharField(help_text="Wiki page path associated with this finding.")
    message = serializers.CharField(help_text="Human-readable explanation of the finding.")


class WikiHealthReportSerializer(serializers.Serializer):
    head_sha = serializers.CharField(help_text="Commit sha inspected by the report.")
    findings = WikiHealthFindingSerializer(many=True, help_text="Health findings for the current wiki head.")


class ChannelWikiPageSerializer(serializers.Serializer):
    """Response shape for a channel's page identity in the wiki."""

    path = serializers.CharField(help_text="Repo-relative path of the wiki page whose frontmatter names the channel.")
    exists = serializers.BooleanField(
        default=True,
        help_text=(
            "Whether a page exists at this path. False when the path is a proposal for a channel "
            "whose page has not been created yet."
        ),
    )


class WikiPageWriteSerializer(serializers.Serializer):
    """Request body for creating or replacing one wiki page."""

    path = serializers.CharField(
        max_length=512,
        help_text="Repo-relative Markdown path inside the wiki's structure, for example `projects/12/spaces/general.md`.",
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
            "A `git bundle` carrying the ref to land, created in the agent's clone "
            "(for example `git bundle create out.bundle origin/main..main`)."
        )
    )
    summary = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=10_000,
        help_text="Optional run summary stored in the landed commit body.",
    )
    branch = serializers.CharField(
        required=False,
        allow_null=True,
        max_length=64,
        help_text=(
            "Land a dated dreaming branch (`dream/<YYYY-MM-DD>`) as one merge commit instead of "
            "rebasing onto `main`. Omit for ordinary commits on `main`."
        ),
    )

    def validate_branch(self, value):  # noqa: ANN001, ANN201
        if value is not None and not DREAM_BRANCH_RE.fullmatch(value):
            raise serializers.ValidationError("Only dream/<YYYY-MM-DD> branches can be landed; omit for main.")
        return value

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
