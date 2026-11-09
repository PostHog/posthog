import dataclasses
from datetime import timedelta
from typing import cast

from django import forms
from django.contrib import messages
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.utils.http import urlencode

from posthog.admin.console.registry import console
from posthog.admin.console.team_panels import DEV_EXPERIENCE
from posthog.admin.console.tools import Cell, ConsoleTool, Notice, Output, Page, Row, Table, ToolOperation
from posthog.dataclasses import frozen
from posthog.models.activity_logging.activity_log import ActivityContextBase, Detail, log_activity
from posthog.models.user import User
from posthog.redis import get_client
from posthog.views import format_bytes

TOOL_URL = "/admin/console/tools/redis-values/"
KEYS_PER_PAGE = 50
MAX_VALUE_DISPLAY_LENGTH = 200
# One key's page shows its value up to this many characters, so a huge key cannot stall the page.
MAX_KEY_PAGE_VALUE_LENGTH = 1024 * 1024
# Ten years. A larger TTL makes no sense for a cache key, and Redis refuses values past its own limit.
MAX_TTL_SECONDS = 10 * 365 * 24 * 60 * 60
# Redis answers TTL with -2 for a key that does not exist and -1 for a key that never expires.
TTL_MISSING_KEY = -2


@dataclasses.dataclass(frozen=True)
class RedisTTLActivityContext(ActivityContextBase):
    reason: str


@frozen
class RedisKeySnapshot:
    key: str
    type: str
    ttl: int
    size: str
    value: str


def _read_value(redis_client, key: str, redis_type: str) -> object:
    if redis_type == "string":
        return redis_client.get(key)
    if redis_type == "hash":
        return redis_client.hgetall(key)
    if redis_type == "zset":
        return redis_client.zrange(key, 0, -1)
    if redis_type == "list":
        return redis_client.lrange(key, 0, -1)
    if redis_type == "set":
        return redis_client.smembers(key)
    return f"(Values of type {redis_type} are not shown.)"


def read_key(redis_client, key: str) -> RedisKeySnapshot:
    redis_type = redis_client.type(key).decode("utf8")
    return RedisKeySnapshot(
        key=key,
        type=redis_type,
        ttl=redis_client.ttl(key),
        size=format_bytes(redis_client.memory_usage(key) or 0),
        value=str(_read_value(redis_client, key, redis_type)),
    )


def _ttl_text(ttl: int) -> str:
    if ttl == -1:
        return "No TTL"
    if ttl == TTL_MISSING_KEY:
        return "Expired"
    return str(timedelta(seconds=ttl))


def _truncate(value: str) -> str:
    return value if len(value) <= MAX_VALUE_DISPLAY_LENGTH else value[:MAX_VALUE_DISPLAY_LENGTH] + "..."


def _key_page_value(value: str) -> str:
    if len(value) <= MAX_KEY_PAGE_VALUE_LENGTH:
        return value
    cut = len(value) - MAX_KEY_PAGE_VALUE_LENGTH
    return (
        f"{value[:MAX_KEY_PAGE_VALUE_LENGTH]}\n\n(Cut {cut:,} more characters. The value is too large to show in full.)"
    )


def _key_url(key: str, cursor: int, pattern: str) -> str:
    return f"{TOOL_URL}?{urlencode({'key': key, 'c': str(cursor), 'q': pattern})}"


def _cursor(request: HttpRequest) -> int:
    raw = request.GET.get("c", "0")
    return int(raw) if raw.isascii() and raw.isdigit() else 0


class SearchKeysForm(forms.Form):
    q = forms.CharField(
        label="Key pattern",
        required=False,
        help_text="A Redis match pattern, for example team_token:*. Leave it empty to list every key.",
    )


class SetTTLForm(forms.Form):
    key = forms.CharField(label="Redis key", strip=False)
    ttl_seconds = forms.IntegerField(
        label="TTL in seconds",
        required=False,
        max_value=MAX_TTL_SECONDS,
        help_text="Leave it empty to remove the TTL, so the key never expires. 0 or less deletes the key now.",
    )
    reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), help_text="Goes into the audit log.")


def search_keys(request: HttpRequest, form: forms.Form | None) -> HttpResponse | Page | None:
    assert form is not None
    pattern = form.cleaned_data["q"]
    return HttpResponseRedirect(f"{TOOL_URL}?{urlencode({'q': pattern})}")


def set_ttl(request: HttpRequest, form: forms.Form | None) -> HttpResponse | Page | None:
    assert form is not None
    key = form.cleaned_data["key"]
    ttl_seconds = form.cleaned_data["ttl_seconds"]
    redis_client = get_client()
    previous_ttl = redis_client.ttl(key)
    if previous_ttl == TTL_MISSING_KEY:
        form.add_error("key", "No Redis key has this name. It may have expired.")
        return HttpResponse(status=404)

    if ttl_seconds is None:
        redis_client.persist(key)
        activity = "ttl_removed"
        detail_name = f"Removed TTL from Redis key {key}"
        messages.success(request, f"Removed the TTL of {key}. It no longer expires.")
    else:
        redis_client.expire(key, ttl_seconds)
        activity = "ttl_updated"
        detail_name = f"Set TTL to {ttl_seconds}s on Redis key {key}"
        messages.success(request, f"Set the TTL of {key} to {ttl_seconds} seconds.")

    # Console routes only answer signed-in staff, so the user is always a User here.
    user = cast(User, request.user)
    organization = user.current_organization
    log_activity(
        organization_id=organization.id if organization is not None else None,
        team_id=None,
        user=user,
        was_impersonated=False,
        item_id=key,
        scope="Admin",
        activity=activity,
        detail=Detail(
            name=detail_name,
            short_id=key,
            type=f"previous_ttl:{previous_ttl}",
            context=RedisTTLActivityContext(reason=form.cleaned_data["reason"]),
        ),
    )
    return None


@console.register_tool
class RedisValuesTool(ConsoleTool):
    key = "redis-values"
    title = "Redis values"
    owner = DEV_EXPERIENCE
    group = "Data"
    description = "The keys in Redis, with their type, TTL, size and value."

    def page(self, request: HttpRequest) -> Page:
        pattern = request.GET.get("q", "")
        cursor = _cursor(request)
        redis_client = get_client()
        key = request.GET.get("key")
        if key:
            return self._key_page(redis_client, key, cursor, pattern)

        next_cursor, raw_keys = redis_client.scan(cursor=cursor, count=KEYS_PER_PAGE, match=pattern or None)
        rows = []
        for raw_key in raw_keys:
            snapshot = read_key(redis_client, raw_key.decode("utf-8"))
            rows.append(
                Row(
                    cells=(
                        Cell(text=snapshot.key, href=_key_url(snapshot.key, cursor, pattern), mono=True),
                        Cell(text=snapshot.type),
                        Cell(text=_ttl_text(snapshot.ttl)),
                        Cell(text=snapshot.size),
                        Cell(text=_truncate(snapshot.value), mono=True),
                    )
                )
            )
        summary = f"Showing {len(rows)} {'key' if len(rows) == 1 else 'keys'}" + (
            f" that match {pattern}." if pattern else "."
        )
        # A Redis SCAN cursor only moves forward, so the page offers the next keys and a way back to the start.
        if next_cursor != 0:
            paging = Notice(
                text=summary,
                link_text="Next keys",
                href=f"{TOOL_URL}?{urlencode({'c': str(next_cursor), 'q': pattern})}",
            )
        elif cursor != 0:
            paging = Notice(text=f"{summary} These are the last keys.", link_text="Back to the start", href=TOOL_URL)
        else:
            paging = Notice(text=summary)
        return Page(
            blocks=(
                paging,
                Table(
                    columns=("Key", "Type", "TTL", "Size", "Value"),
                    rows=tuple(rows),
                    empty_text="No keys on this page. Search with another pattern, or go to the next keys.",
                ),
            )
        )

    def _key_page(self, redis_client, key: str, cursor: int, pattern: str) -> Page:
        back = f"{TOOL_URL}?{urlencode({'c': str(cursor), 'q': pattern})}"
        if redis_client.ttl(key) == TTL_MISSING_KEY:
            return Page(
                blocks=(
                    Notice(text=f"No Redis key {key}. It may have expired.", link_text="Back to the keys", href=back),
                )
            )
        snapshot = read_key(redis_client, key)
        return Page(
            blocks=(
                Notice(
                    text=f"{snapshot.key} · {snapshot.type} · TTL: {_ttl_text(snapshot.ttl)} · {snapshot.size}",
                    link_text="Back to the keys",
                    href=back,
                ),
                Output(text=_key_page_value(snapshot.value)),
            )
        )

    def operations(self, request: HttpRequest) -> list[ToolOperation]:
        key = request.GET.get("key", "")
        ttl_initial: dict[str, object] = {"key": key}
        if key:
            ttl = get_client().ttl(key)
            if ttl > 0:
                ttl_initial["ttl_seconds"] = ttl
        return [
            ToolOperation(
                key="search",
                label="Search keys",
                handler=search_keys,
                description="Lists the keys that match a pattern.",
                form_class=SearchKeysForm,
                form_initial={"q": request.GET.get("q", "")},
            ),
            ToolOperation(
                key="set-ttl",
                label="Set TTL",
                handler=set_ttl,
                danger=True,
                description="Changes when a key expires. A key past its TTL is deleted.",
                form_class=SetTTLForm,
                form_initial=ttl_initial,
                undo_hint=(
                    "Set the TTL again. A key that expired is deleted and cannot be restored, so its cache fills "
                    "again on the next read, or its data is lost."
                ),
            ),
        ]
