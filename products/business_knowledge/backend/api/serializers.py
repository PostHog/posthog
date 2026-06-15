"""DRF serializers for business_knowledge."""

from urllib.parse import urlparse

from django.core.files.uploadedfile import UploadedFile
from django.utils import timezone

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from posthog.security.url_validation import is_url_allowed

from .. import github, url_fetch
from ..constants import (
    CRAWL_HARD_MAX_DEPTH,
    DEFAULT_CRAWL_MAX_DEPTH,
    DEFAULT_MAX_PAGES,
    GITHUB_DEFAULT_INCLUDE_GLOBS,
    MAX_FILE_SIZE_BYTES,
    MAX_TEXT_SIZE_BYTES,
    MAX_URLS_PER_SOURCE,
)
from ..models import (
    REFRESH_INTERVAL_TIMEDELTAS,
    CrawlMode,
    EmbeddingStatus,
    KnowledgeSource,
    RefreshInterval,
    SourceType,
)


def _derive_scope_globs(url: str) -> list[str]:
    """
    Auto-derive include globs from the entry URL path so that same-origin
    crawls are scoped to the URL's section by default.

    - Root path (``/`` or empty) → empty list (crawl the whole origin).
    - Non-root → ``[path, path/*]`` to match the index page + descendants
      without sibling bleed (e.g. ``/docs/support`` won't grab ``/docs/support-center``).
    """
    path = urlparse(url).path.rstrip("/") or "/"
    if path == "/":
        return []
    return [path, f"{path}/*"]


class _GlobListField(serializers.ListField):
    """
    Tiny wrapper so each entry is validated as a non-empty string and the
    total list is bounded. Keeps the glob inputs from being used as a DoS
    vector — fnmatch is cheap but not free per-URL.
    """

    child = serializers.CharField(max_length=256)
    max_length = 32


class _NameValidationMixin:
    def validate_name(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Name cannot be blank.")
        return value


class _UrlValidationMixin:
    def validate_url(self, value: str) -> str:
        try:
            normalized = url_fetch.normalize_url(value)
        except url_fetch.UrlFetchError:
            raise serializers.ValidationError("Invalid URL.")
        allowed, _reason = is_url_allowed(normalized)
        if not allowed:
            raise serializers.ValidationError("URL is not reachable.")
        return normalized


class KnowledgeSourceSerializer(serializers.ModelSerializer):
    document_count = serializers.IntegerField(
        source="_document_count",
        read_only=True,
        default=0,
        help_text="Number of documents belonging to this source.",
    )
    chunk_count = serializers.IntegerField(
        source="_chunk_count",
        read_only=True,
        default=0,
        help_text="Number of chunks belonging to this source.",
    )
    next_refresh_at = serializers.SerializerMethodField(
        help_text="When the background coordinator will next auto-refresh this source. Null for manual sources or sources never refreshed.",
    )
    has_unsafe_documents = serializers.SerializerMethodField(
        help_text="True when at least one document in this source was flagged unsafe by the content classifier and is therefore excluded from agent search.",
    )
    embedding_status = serializers.SerializerMethodField(
        help_text=(
            "Semantic-index state of this source. A `ready` source serves keyword (full-text) search "
            "immediately, but semantic search needs a background job to classify and embed its documents, "
            "which can take up to an hour. `pending` — at least one document is still awaiting "
            "classification or embedding. `completed` — every eligible document has been submitted to the "
            "embedding pipeline. `disabled` — the organization has not approved AI data processing, so "
            "embeddings never run and search stays keyword-only. Only meaningful while `status` is `ready`."
        ),
    )

    class Meta:
        model = KnowledgeSource
        fields = [
            "id",
            "team_id",
            "name",
            "source_type",
            "status",
            "error_message",
            "document_count",
            "chunk_count",
            "created_at",
            "updated_at",
            "source_url",
            "last_refresh_at",
            "last_refresh_status",
            "last_refresh_error",
            "refresh_interval",
            "next_refresh_at",
            "has_unsafe_documents",
            "embedding_status",
            "crawl_mode",
            "crawl_config",
            "original_filename",
            "file_content_type",
            "file_size_bytes",
        ]
        read_only_fields = fields

    def get_next_refresh_at(self, obj: KnowledgeSource) -> str | None:
        delta = REFRESH_INTERVAL_TIMEDELTAS.get(obj.refresh_interval)
        if delta is None:
            # `manual` (or unknown) interval — no auto-refresh scheduled.
            return None
        if obj.last_refresh_at is None:
            # On a cadence but never refreshed: `list_due_refresh_sources`
            # treats this as immediately due, so surface "now" not null.
            return timezone.now().isoformat()
        return (obj.last_refresh_at + delta).isoformat()

    def get_has_unsafe_documents(self, obj: KnowledgeSource) -> bool:
        # Annotated by the logic layer to avoid an N+1 in list responses.
        return bool(getattr(obj, "_has_unsafe_documents", False))

    @extend_schema_field(serializers.ChoiceField(choices=EmbeddingStatus.choices))
    def get_embedding_status(self, obj: KnowledgeSource) -> str:
        # Both inputs are annotated by the logic layer (list_for_team /
        # get_for_team) to avoid N+1s. When a source is serialized without
        # annotations (future code path), fall back to a live DB query for
        # both rather than silently returning the wrong value.
        if hasattr(obj, "_ai_processing_approved"):
            approved = bool(obj._ai_processing_approved)
        else:
            approved = bool(obj.team.organization.is_ai_data_processing_approved)
        if not approved:
            return EmbeddingStatus.DISABLED
        if hasattr(obj, "_has_pending_embeddings"):
            pending = bool(obj._has_pending_embeddings)
        else:
            from .. import logic

            pending = logic.has_pending_embeddings(obj.id)
        if pending:
            return EmbeddingStatus.PENDING
        return EmbeddingStatus.COMPLETED


class CreateTextSourceSerializer(_NameValidationMixin, serializers.Serializer):
    name = serializers.CharField(
        max_length=255,
        help_text="Short human label for the source. Shown in the settings list and in agent citations.",
    )
    text = serializers.CharField(
        trim_whitespace=False,
        help_text=(
            "Raw text to index. Capped at 1 MB; larger payloads should be split into multiple sources "
            "or wait for URL/file support in Stage 2/3."
        ),
    )

    def validate_text(self, value: str) -> str:
        if not value.strip():
            raise serializers.ValidationError("Text cannot be blank.")
        if len(value.encode("utf-8")) > MAX_TEXT_SIZE_BYTES:
            raise serializers.ValidationError(
                f"Text exceeds the {MAX_TEXT_SIZE_BYTES:,}-byte cap. Split it into smaller sources."
            )
        return value

    def to_internal_value(self, data: dict) -> dict:
        attrs = super().to_internal_value(data)
        attrs["source_type"] = SourceType.TEXT.value
        return attrs


class UpdateTextSourceSerializer(_NameValidationMixin, serializers.Serializer):
    """
    PATCH payload for text sources. Both fields optional, at least one
    required. `text` triggers a re-chunk; `name` alone does not.
    """

    name = serializers.CharField(
        max_length=255,
        required=False,
        help_text="New human label for the source.",
    )
    text = serializers.CharField(
        required=False,
        trim_whitespace=False,
        help_text="Replacement text. Omit to keep the existing content.",
    )

    def validate_text(self, value: str) -> str:
        if not value.strip():
            raise serializers.ValidationError("Text cannot be blank.")
        if len(value.encode("utf-8")) > MAX_TEXT_SIZE_BYTES:
            raise serializers.ValidationError(
                f"Text exceeds the {MAX_TEXT_SIZE_BYTES:,}-byte cap. Split it into smaller sources."
            )
        return value

    def validate(self, attrs: dict) -> dict:
        if "name" not in attrs and "text" not in attrs:
            raise serializers.ValidationError("Provide at least one of `name` or `text`.")
        return attrs


class UpdateUrlSourceSerializer(_NameValidationMixin, _UrlValidationMixin, serializers.Serializer):
    """
    PATCH payload for URL sources. All fields optional, at least one required.
    Changing `url` or crawl settings triggers a re-crawl.
    """

    name = serializers.CharField(
        max_length=255,
        required=False,
        help_text="New human label for the source.",
    )
    url = serializers.URLField(
        max_length=2048,
        required=False,
        help_text="New URL. Triggers a re-crawl when changed.",
    )
    crawl_mode = serializers.ChoiceField(
        choices=[
            CrawlMode.SINGLE.value,
            CrawlMode.SITEMAP.value,
            CrawlMode.SAME_ORIGIN.value,
            CrawlMode.GITHUB_REPO.value,
        ],
        required=False,
        help_text="New crawl mode. Triggers a re-crawl when changed.",
    )
    refresh_interval = serializers.ChoiceField(
        choices=RefreshInterval.choices,
        required=False,
        help_text="How often to auto-refresh this source in the background. `manual` disables auto-refresh. Changing it alone does not trigger a re-crawl.",
    )
    include_globs = _GlobListField(
        required=False,
        help_text="URL path globs to include.",
    )
    exclude_globs = _GlobListField(
        required=False,
        help_text="URL path globs to exclude.",
    )
    max_pages = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=MAX_URLS_PER_SOURCE,
        help_text=f"Max pages to fetch. Capped at {MAX_URLS_PER_SOURCE}.",
    )
    max_depth = serializers.IntegerField(
        required=False,
        min_value=0,
        max_value=CRAWL_HARD_MAX_DEPTH,
        help_text="BFS depth for same_origin.",
    )

    def validate(self, attrs: dict) -> dict:
        if not attrs:
            raise serializers.ValidationError("Provide at least one field to update.")
        current_source = self.instance if isinstance(self.instance, KnowledgeSource) else None
        crawl_mode = attrs.get("crawl_mode", current_source.crawl_mode if current_source else None)
        url = attrs.get("url", current_source.source_url if current_source else None)
        # Validate the effective URL whenever the source is (or becomes) a GitHub
        # source, even when the client only updates `url` and omits `crawl_mode`.
        if crawl_mode == CrawlMode.GITHUB_REPO.value and url:
            try:
                github.parse_repo_url(url)
            except github.GithubError as exc:
                raise serializers.ValidationError({"url": str(exc)})
        return attrs

    def to_internal_value(self, data: dict) -> dict:
        attrs = super().to_internal_value(data)
        crawl_config_keys = {"include_globs", "exclude_globs", "max_pages", "max_depth"}
        crawl_fields = {k: attrs.pop(k) for k in crawl_config_keys if k in attrs}
        current_source = self.instance if isinstance(self.instance, KnowledgeSource) else None
        crawl_mode = attrs.get("crawl_mode", current_source.crawl_mode if current_source else data.get("crawl_mode"))
        entered_github_mode = crawl_mode == CrawlMode.GITHUB_REPO.value and (
            current_source is None or current_source.crawl_mode != CrawlMode.GITHUB_REPO.value
        )
        # Re-derive scope when include_globs was NOT sent (user didn't override),
        # the URL is changing, and mode is same-origin.
        if "include_globs" not in crawl_fields and "url" in attrs:
            if crawl_mode == CrawlMode.SAME_ORIGIN.value:
                crawl_fields["include_globs"] = _derive_scope_globs(attrs["url"])
            elif crawl_mode == CrawlMode.GITHUB_REPO.value and (
                entered_github_mode
                or not isinstance(getattr(current_source, "crawl_config", None), dict)
                or not (current_source.crawl_config or {}).get("include_globs")
            ):
                crawl_fields["include_globs"] = list(GITHUB_DEFAULT_INCLUDE_GLOBS)

        if crawl_mode == CrawlMode.GITHUB_REPO.value:
            repo_url = attrs.get("url", current_source.source_url if current_source else None)
            if repo_url and (entered_github_mode or "url" in attrs):
                # Keep `crawl_config.ref` in sync with the selected tree URL.
                crawl_fields["ref"] = github.parse_repo_url(repo_url).ref
        if crawl_fields:
            attrs["crawl_config"] = crawl_fields
        return attrs


class CreateUrlSourceSerializer(_NameValidationMixin, _UrlValidationMixin, serializers.Serializer):
    """
    POST payload for URL sources. Normalizes + SSRF-validates the URL here
    so the client gets a precise 400 instead of a created-but-errored source.
    The logic layer re-validates on every fetch anyway — this is UX, not
    security.
    """

    name = serializers.CharField(
        max_length=255,
        help_text="Short human label for the source. Shown in the settings list and in agent citations.",
    )
    url = serializers.URLField(
        max_length=2048,
        help_text=(
            "Public HTTP(S) URL to fetch. Private / internal hosts are rejected. "
            "Stage 2a fetches this URL once at create time; Stage 5 will refresh it on a schedule."
        ),
    )
    refresh_interval = serializers.ChoiceField(
        choices=RefreshInterval.choices,
        required=False,
        default=RefreshInterval.MANUAL,
        help_text="How often to auto-refresh this source in the background. `manual` disables auto-refresh.",
    )

    def to_internal_value(self, data: dict) -> dict:
        attrs = super().to_internal_value(data)
        attrs["source_type"] = SourceType.URL.value
        return attrs


class CreateCrawlSourceSerializer(_NameValidationMixin, _UrlValidationMixin, serializers.Serializer):
    """
    POST payload for multi-URL crawl sources (Stage 2b).

    The entry URL goes through the same SSRF gate as the single-URL endpoint;
    each URL discovered during the crawl is independently re-validated before
    fetch, so we never trust a discovered URL just because its parent did.
    """

    name = serializers.CharField(
        max_length=255,
        help_text="Short human label for the source. Shown in the settings list and in agent citations.",
    )
    url = serializers.URLField(
        max_length=2048,
        help_text="Entry URL. For sitemap mode, this is sitemap.xml (or a page whose origin has /sitemap.xml).",
    )
    crawl_mode = serializers.ChoiceField(
        choices=[CrawlMode.SITEMAP.value, CrawlMode.SAME_ORIGIN.value, CrawlMode.GITHUB_REPO.value],
        help_text="How to expand the entry URL into documents.",
    )
    refresh_interval = serializers.ChoiceField(
        choices=RefreshInterval.choices,
        required=False,
        default=RefreshInterval.MANUAL,
        help_text="How often to auto-refresh this source in the background. `manual` disables auto-refresh.",
    )
    include_globs = _GlobListField(
        required=False,
        default=list,
        help_text="URL path globs to include (fnmatch, e.g. `/docs/*`). Empty means include everything.",
    )
    exclude_globs = _GlobListField(
        required=False,
        default=list,
        help_text="URL path globs to exclude. Applied after `include_globs`.",
    )
    max_pages = serializers.IntegerField(
        required=False,
        default=DEFAULT_MAX_PAGES,
        min_value=1,
        max_value=MAX_URLS_PER_SOURCE,
        help_text=f"Max pages to fetch. Capped at {MAX_URLS_PER_SOURCE} for inline crawls.",
    )
    max_depth = serializers.IntegerField(
        required=False,
        default=DEFAULT_CRAWL_MAX_DEPTH,
        min_value=0,
        max_value=CRAWL_HARD_MAX_DEPTH,
        help_text="BFS depth for `same_origin`. Ignored by `sitemap`.",
    )

    def validate(self, attrs: dict) -> dict:
        attrs = super().validate(attrs)
        if attrs.get("crawl_mode") == CrawlMode.GITHUB_REPO.value:
            try:
                github.parse_repo_url(attrs["url"])
            except github.GithubError as exc:
                raise serializers.ValidationError({"url": str(exc)})
        return attrs

    def to_internal_value(self, data: dict) -> dict:
        attrs = super().to_internal_value(data)
        attrs["source_type"] = SourceType.URL.value

        crawl_mode = attrs.get("crawl_mode")
        include_globs = attrs.pop("include_globs")
        exclude_globs = attrs.pop("exclude_globs")
        max_pages = attrs.pop("max_pages")
        max_depth = attrs.pop("max_depth")

        if crawl_mode == CrawlMode.GITHUB_REPO.value:
            if not include_globs:
                include_globs = list(GITHUB_DEFAULT_INCLUDE_GLOBS)
            try:
                repo_info = github.parse_repo_url(attrs["url"])
                ref = repo_info.ref
            except github.GithubError:
                ref = None
            attrs["crawl_config"] = {
                "include_globs": include_globs,
                "exclude_globs": exclude_globs,
                "max_pages": max_pages,
                "ref": ref,
            }
        else:
            if not include_globs and crawl_mode == CrawlMode.SAME_ORIGIN.value:
                include_globs = _derive_scope_globs(attrs["url"])
            attrs["crawl_config"] = {
                "include_globs": include_globs,
                "exclude_globs": exclude_globs,
                "max_pages": max_pages,
                "max_depth": max_depth,
            }
        return attrs


class KnowledgeDocumentWindowSerializer(serializers.Serializer):
    """
    One chunk in a drill-down window over a single knowledge document.

    Output-only — the rows come from the `get_document_window` logic helper
    (a `KnowledgeSearchResult` dataclass), not the ORM, so this is a plain
    read serializer rather than a `ModelSerializer`.
    """

    chunk_id = serializers.UUIDField(
        read_only=True,
        help_text="Stable identifier of this chunk. Same value used in search results.",
    )
    ordinal = serializers.IntegerField(
        read_only=True,
        help_text="Zero-based position of this chunk within its document. Use it as `around_ordinal` to recenter the window.",
    )
    content = serializers.CharField(
        read_only=True,
        help_text="The chunk's text content.",
    )
    heading_path = serializers.CharField(
        read_only=True,
        help_text="Breadcrumb of section headings this chunk sits under. Empty when the document has no heading structure.",
    )
    source_name = serializers.CharField(
        read_only=True,
        help_text="Human label of the knowledge source this chunk belongs to.",
    )
    document_title = serializers.CharField(
        read_only=True,
        help_text="Title of the document this chunk belongs to.",
    )


class KnowledgeSearchResultSerializer(serializers.Serializer):
    """
    One ranked chunk from a business knowledge search.

    Output-only — the rows come from the ``search_knowledge_for_team`` logic
    helper (a ``KnowledgeSearchResult`` dataclass), not the ORM.
    """

    chunk_id = serializers.UUIDField(
        read_only=True,
        help_text="Stable identifier of this chunk.",
    )
    document_id = serializers.UUIDField(
        read_only=True,
        help_text="ID of the parent document. Pass to the document-window endpoint with `around_ordinal` to drill down.",
    )
    ordinal = serializers.IntegerField(
        read_only=True,
        help_text="Zero-based position of this chunk within its document. Use as `around_ordinal` in the document-window endpoint.",
    )
    source_id = serializers.UUIDField(
        read_only=True,
        help_text="ID of the knowledge source this chunk belongs to.",
    )
    source_name = serializers.CharField(
        read_only=True,
        help_text="Human label of the knowledge source this chunk belongs to.",
    )
    source_type = serializers.CharField(
        read_only=True,
        help_text="Source type (text, url, or file).",
    )
    document_title = serializers.CharField(
        read_only=True,
        help_text="Title of the document this chunk belongs to.",
    )
    heading_path = serializers.CharField(
        read_only=True,
        help_text="Breadcrumb of section headings this chunk sits under. Empty when the document has no heading structure.",
    )
    content = serializers.CharField(
        read_only=True,
        help_text="The chunk's text content.",
    )


class CreateFileSourceSerializer(_NameValidationMixin, serializers.Serializer):
    """
    Multipart upload payload for file sources. The file's content type is
    detected from magic bytes server-side — the client-provided Content-Type
    is ignored for security.
    """

    name = serializers.CharField(
        max_length=255,
        help_text="Short human label for the source.",
    )
    file = serializers.FileField(
        help_text=(
            f"PDF, DOCX, Markdown (.md), CSV, or plain text (.txt) file. Max {MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB."
        ),
    )

    def validate_file(self, value: UploadedFile) -> UploadedFile:  # noqa: F821
        if value.size and value.size > MAX_FILE_SIZE_BYTES:
            raise serializers.ValidationError(f"File exceeds the {MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB cap.")
        return value
