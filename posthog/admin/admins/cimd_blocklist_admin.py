"""Admin for the CIMD partner-URL blocklist.

Deleting a CIMD ``OAuthApplication`` auto-blocklists its metadata URL (see
``_block_cimd_url_on_application_delete``), so the partner cannot immediately register again
from the same document. Without a place to see and clear those entries, the only symptom is
every authorize request for that client_id failing with "Invalid client_id parameter value",
and the only cure is a shell.

Writes here go through ``block_cimd_url`` and ``unblock_cimd_url`` instead of the ORM. The
verdict lives in Postgres and in Redis, and ``is_cimd_url_blocked`` caches either answer for
a year, so an ORM-only write leaves the stale cache in charge: a row deleted by hand keeps
the URL blocked, and a row added by hand never takes effect.
"""

from typing import cast

from django.contrib import admin
from django.db.models import QuerySet
from django.forms import ModelForm
from django.http import HttpRequest

from posthog.api.oauth.cimd import block_cimd_url, cimd_block_cache_state, unblock_cimd_url
from posthog.models import User
from posthog.models.oauth import CIMDBlocklistEntry


class CIMDBlocklistEntryForm(ModelForm):
    class Meta:
        model = CIMDBlocklistEntry
        fields = "__all__"
        help_texts = {
            "cimd_url": (
                "Paste the exact client_id from the OAuth application row. Matching is byte for byte, "
                "so a different host case, a trailing slash or an explicit :443 never matches. "
                "Deleting an entry unblocks the URL: the next authorize request fetches the metadata "
                "document again and recreates the application."
            )
        }


@admin.register(CIMDBlocklistEntry)
class CIMDBlocklistEntryAdmin(admin.ModelAdmin):
    form = CIMDBlocklistEntryForm
    list_display = ("cimd_url", "reason", "cache_state", "created_at", "created_by")
    list_display_links = ("cimd_url",)
    search_fields = ("cimd_url", "reason")
    ordering = ("-created_at",)

    def get_readonly_fields(self, request: HttpRequest, obj: CIMDBlocklistEntry | None = None) -> tuple[str, ...]:
        # cimd_url derives the Redis key, so changing it on an existing entry would strand the
        # old key as a permanent block on a URL that no longer has a row. Set it once, on add.
        base = ("created_at", "created_by")
        return base if obj is None else ("cimd_url", *base)

    @admin.display(description="Cache")
    def cache_state(self, entry: CIMDBlocklistEntry) -> str:
        # Authorize reads the cache before Postgres, so an entry the cache disagrees with is
        # not actually enforced. Show the two apart instead of implying the row is the truth.
        state = cimd_block_cache_state(entry.cimd_url)
        if state is None:
            return "not cached (warms to blocked)"
        return "blocked" if state else "STALE: cached as allowed"

    def save_model(self, request: HttpRequest, obj: CIMDBlocklistEntry, form: ModelForm, change: bool) -> None:
        if not change:
            # The admin site requires a logged-in staff user, so request.user is never anonymous.
            obj.created_by = cast(User, request.user)
        super().save_model(request, obj, form, change)
        # Write the Redis key too. A URL that authorize resolved before has its allowed
        # verdict cached for a year, so a row on its own would sit here looking authoritative
        # while the client kept working.
        block_cimd_url(obj.cimd_url, reason=obj.reason, created_by=obj.created_by)

    def delete_model(self, request: HttpRequest, obj: CIMDBlocklistEntry) -> None:
        unblock_cimd_url(obj.cimd_url)

    def delete_queryset(self, request: HttpRequest, queryset: QuerySet[CIMDBlocklistEntry]) -> None:
        for url in list(queryset.values_list("cimd_url", flat=True)):
            unblock_cimd_url(url)
