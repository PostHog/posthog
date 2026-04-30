"""
DRF serializers for business_knowledge.

Output: `KnowledgeSourceSerializer` is a DataclassSerializer over the DTO so
the generated TypeScript types follow the contract automatically.

Input: `CreateTextSourceSerializer` validates the raw text payload. Size /
quota checks that need DB access live in logic.py and are raised during
create_text_source inside the transaction.
"""

from django.core.files.uploadedfile import UploadedFile

from rest_framework import serializers
from rest_framework_dataclasses.serializers import DataclassSerializer

from posthog.security.url_validation import is_url_allowed

from .. import url_fetch
from ..facade.contracts import KnowledgeSourceDTO
from ..facade.enums import (
    CRAWL_HARD_MAX_DEPTH,
    DEFAULT_CRAWL_MAX_DEPTH,
    DEFAULT_MAX_PAGES,
    MAX_FILE_SIZE_BYTES,
    MAX_TEXT_SIZE_BYTES,
    MAX_URLS_PER_SOURCE,
    SourceType,
)
from ..models import CrawlMode


class _GlobListField(serializers.ListField):
    """
    Tiny wrapper so each entry is validated as a non-empty string and the
    total list is bounded. Keeps the glob inputs from being used as a DoS
    vector — fnmatch is cheap but not free per-URL.
    """

    child = serializers.CharField(max_length=256)
    max_length = 32


class KnowledgeSourceSerializer(DataclassSerializer):
    class Meta:
        dataclass = KnowledgeSourceDTO


class CreateTextSourceSerializer(serializers.Serializer):
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

    def validate_name(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Name cannot be blank.")
        return value

    def validate_text(self, value: str) -> str:
        if not value.strip():
            raise serializers.ValidationError("Text cannot be blank.")
        # Mirror the logic.py byte cap here so we can 400 before opening a transaction.
        if len(value.encode("utf-8")) > MAX_TEXT_SIZE_BYTES:
            raise serializers.ValidationError(
                f"Text exceeds the {MAX_TEXT_SIZE_BYTES:,}-byte cap. Split it into smaller sources."
            )
        return value

    def to_internal_value(self, data: dict) -> dict:
        attrs = super().to_internal_value(data)
        # Pin the source_type server-side — clients cannot opt into url/file
        # via this endpoint. Those get their own endpoints in Stage 2/3.
        attrs["source_type"] = SourceType.TEXT.value
        return attrs


class UpdateTextSourceSerializer(serializers.Serializer):
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

    def validate_name(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Name cannot be blank.")
        return value

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


class UpdateUrlSourceSerializer(serializers.Serializer):
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
        choices=[CrawlMode.SINGLE.value, CrawlMode.SITEMAP.value, CrawlMode.SAME_ORIGIN.value],
        required=False,
        help_text="New crawl mode. Triggers a re-crawl when changed.",
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

    def validate_name(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Name cannot be blank.")
        return value

    def validate_url(self, value: str) -> str:
        try:
            normalized = url_fetch.normalize_url(value)
        except url_fetch.UrlFetchError:
            raise serializers.ValidationError("Invalid URL.")
        allowed, _reason = is_url_allowed(normalized)
        if not allowed:
            raise serializers.ValidationError("URL is not reachable.")
        return normalized

    def validate(self, attrs: dict) -> dict:
        if not attrs:
            raise serializers.ValidationError("Provide at least one field to update.")
        return attrs

    def to_internal_value(self, data: dict) -> dict:
        attrs = super().to_internal_value(data)
        crawl_config_keys = {"include_globs", "exclude_globs", "max_pages", "max_depth"}
        crawl_fields = {k: attrs.pop(k) for k in crawl_config_keys if k in attrs}
        if crawl_fields:
            attrs["crawl_config"] = crawl_fields
        return attrs


class CreateUrlSourceSerializer(serializers.Serializer):
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

    def validate_name(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Name cannot be blank.")
        return value

    def validate_url(self, value: str) -> str:
        try:
            normalized = url_fetch.normalize_url(value)
        except url_fetch.UrlFetchError:
            raise serializers.ValidationError("Invalid URL.")
        allowed, reason = is_url_allowed(normalized)
        if not allowed:
            # Don't echo the exact SSRF reason — it's a reconnaissance aid.
            # A generic message is enough for the user.
            raise serializers.ValidationError("URL is not reachable.")
        return normalized

    def to_internal_value(self, data: dict) -> dict:
        attrs = super().to_internal_value(data)
        attrs["source_type"] = SourceType.URL.value
        return attrs


class CreateCrawlSourceSerializer(serializers.Serializer):
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
        choices=[CrawlMode.SITEMAP.value, CrawlMode.SAME_ORIGIN.value],
        help_text="How to expand the entry URL into documents.",
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

    def validate_name(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Name cannot be blank.")
        return value

    def validate_url(self, value: str) -> str:
        try:
            normalized = url_fetch.normalize_url(value)
        except url_fetch.UrlFetchError:
            raise serializers.ValidationError("Invalid URL.")
        allowed, _reason = is_url_allowed(normalized)
        if not allowed:
            raise serializers.ValidationError("URL is not reachable.")
        return normalized

    def to_internal_value(self, data: dict) -> dict:
        attrs = super().to_internal_value(data)
        # Flatten the per-field knobs into `crawl_config` for the facade.
        attrs["source_type"] = SourceType.URL.value
        attrs["crawl_config"] = {
            "include_globs": attrs.pop("include_globs"),
            "exclude_globs": attrs.pop("exclude_globs"),
            "max_pages": attrs.pop("max_pages"),
            "max_depth": attrs.pop("max_depth"),
        }
        return attrs


class CreateFileSourceSerializer(serializers.Serializer):
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

    def validate_name(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Name cannot be blank.")
        return value

    def validate_file(self, value: UploadedFile) -> UploadedFile:  # noqa: F821
        if value.size and value.size > MAX_FILE_SIZE_BYTES:
            raise serializers.ValidationError(f"File exceeds the {MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB cap.")
        return value
