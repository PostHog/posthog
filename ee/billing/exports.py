"""What the billing exports and series share between the root reads and the organization API:
labels for project series, the CSV label rewrite, gzip and chunk streaming, and the per-person
budget of exports downloading at once."""

import io
import csv
import zlib
from collections.abc import AsyncGenerator, Iterator, Sequence
from typing import Any, Optional

from django.conf import settings

import requests
from asgiref.sync import sync_to_async
from rest_framework.exceptions import Throttled

from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded, ConcurrencySlot, RateLimit
from posthog.models import Organization, Team, User
from posthog.utils import generate_short_id

from products.access_control.backend.facade.user_access_control import UserAccessControl


def _gzip_stream(chunks: Iterator[bytes]) -> Iterator[bytes]:
    """One gzip stream for the whole file, flushed after every chunk.

    Django's gzip middleware compresses an asynchronous body one chunk at a time, each as its
    own gzip member, and a browser stops reading at the end of the first member. Compressing
    here as a single stream, with a sync flush after each chunk so every chunk goes out as soon
    as it is read, and setting Content-Encoding on the response makes the middleware leave it
    alone. Compressing is safe against BREACH here: the body is usage numbers and project names,
    with no CSRF token or other secret reflected in it.
    """
    compressor = zlib.compressobj(6, zlib.DEFLATED, 16 + zlib.MAX_WBITS)
    for chunk in chunks:
        data = compressor.compress(chunk) + compressor.flush(zlib.Z_SYNC_FLUSH)
        if data:
            yield data
    yield compressor.flush()


# How many exports one person may have downloading at once. Each holds a response from billing
# open for as long as the browser reads it, so the count is bounded per person and a slot is
# given back when the download ends or the connection drops. The time limit only frees a slot
# whose download died without giving it back.
_EXPORT_STREAMS = RateLimit(
    max_concurrency=settings.BILLING_EXPORT_CONCURRENT_STREAMS,
    limit_name="billing_export_streams",
    get_task_name=lambda user_id: f"billing_export_streams:{user_id}",
    get_task_id=lambda user_id: generate_short_id(),
    ttl=15 * 60,
    apply_clickhouse_kill_switch=False,
    allow_team_bypass=False,
)


def _take_export_stream_slot(user: Any) -> Optional[ConcurrencySlot]:
    try:
        return _EXPORT_STREAMS.use(user.pk)
    except ConcurrencyLimitExceeded:
        raise Throttled(
            detail=(
                f"You have {settings.BILLING_EXPORT_CONCURRENT_STREAMS} exports downloading. "
                "Wait for one to finish before starting another."
            )
        )


def _release_export_stream_slot(slot: Optional[ConcurrencySlot]) -> None:
    if slot is not None:
        _EXPORT_STREAMS.release(slot)


async def _released_after(stream: AsyncGenerator[bytes], slot: Optional[ConcurrencySlot]) -> AsyncGenerator[bytes]:
    """Give the export's stream slot back when the download ends, however it ends."""
    try:
        async for chunk in stream:
            yield chunk
    finally:
        await sync_to_async(_release_export_stream_slot)(slot)


async def _stream_chunks(upstream: requests.Response, chunks: Iterator[bytes]) -> AsyncGenerator[bytes]:
    """Hand the file to the ASGI server one chunk at a time.

    Django 5 consumes a synchronous iterator in full before an ASGI server sends anything -
    StreamingHttpResponse.__aiter__ calls sync_to_async(list) on it - so a large export would
    arrive all at once at the end. Pulling each chunk on a worker thread keeps the body
    asynchronous, and it goes out as billing produces it. The upstream response is closed when
    the consumer stops, which is also what happens when the browser cancels the download.
    """
    iterator = iter(chunks)

    def pull() -> bytes | None:
        return next(iterator, None)

    try:
        while True:
            chunk = await sync_to_async(pull, thread_sensitive=False)()
            if chunk is None:
                return
            yield chunk
    finally:
        upstream.close()


def _rewrite_csv_labels(chunks: Iterator[bytes], teams_map: dict[int, str]) -> Iterator[bytes]:
    """Put project names into an exported CSV as it streams through, in place of ids.

    Billing has no project names, so its Project column carries the id, and the name goes in
    here. The Project ID column beside it keeps the id: names are not unique inside an
    organization. Sending billing an id-to-name map instead would put every project's name in
    the request, and an export usually asks for every project.

    Rows are rewritten one line at a time so the response keeps streaming. Fields are parsed and
    written with the csv module rather than string-replaced, because project names contain
    commas and quotes.
    """
    names = {str(team_id): name for team_id, name in teams_map.items()}
    pending = b""

    def rewrite(line: str) -> str:
        row = next(csv.reader([line]), None)
        if not row or len(row) < 3:
            return line
        project, team_id = row[1], row[2]
        # Only a Project cell that is a bare id gets a name. The header, a row with no project, the
        # folded "all other projects" row, and an id PostHog has no name for (a project deleted since
        # the usage was recorded) pass through unchanged.
        if project != team_id or team_id not in names:
            return line
        name = names[team_id]
        # A spreadsheet runs a cell starting with =, +, -, @, a tab or a carriage return as a
        # formula, and project names are typed by users; a leading quote keeps the cell text.
        row[1] = f"'{name}" if name and name[0] in ("=", "+", "-", "@", "\t", "\r") else name
        buffer = io.StringIO()
        csv.writer(buffer, lineterminator="").writerow(row)
        return buffer.getvalue()

    for chunk in chunks:
        pending += chunk
        *lines, pending = pending.split(b"\n")
        for line in lines:
            yield rewrite(line.decode("utf-8")).encode("utf-8") + b"\n"
    if pending:
        yield rewrite(pending.decode("utf-8")).encode("utf-8")


def _resolve_team_labels(results: Any, teams_map: dict[int, str]) -> None:
    """Put project names into the series labels, in place.

    Billing keys usage by project id, so its labels carry the id: "134::Events". The name goes
    in here rather than being sent to billing as an id-to-name map, which for an organization
    with several hundred projects is about 16KB of query string on every request. The id comes
    back in breakdown_value, so the label is rebuilt from that rather than parsed. A series whose
    id has no name, the folded "all other projects" series or a deleted project, keeps the label
    billing produced.
    """
    if not isinstance(results, list):
        return

    names = {str(team_id): name for team_id, name in teams_map.items()}
    for series in results:
        if not isinstance(series, dict):
            continue
        breakdown_value = series.get("breakdown_value")
        label = series.get("label")
        if not isinstance(label, str):
            continue

        if series.get("breakdown_type") == "multiple" and isinstance(breakdown_value, list):
            if len(breakdown_value) != 2:
                continue
            name = names.get(str(breakdown_value[1]))
            # Only the project part is replaced. The product part after the first separator may contain
            # separators of its own.
            _, separator, remainder = label.partition("::")
            if name and separator:
                series["label"] = f"{name}{separator}{remainder}"
        elif series.get("breakdown_type") == "team" and breakdown_value is not None:
            name = names.get(str(breakdown_value))
            if name:
                series["label"] = name


def exportable_team_ids(user: Any, organization: Organization, team_ids: Sequence[int]) -> Sequence[int]:
    """The given projects on which the person has editor access to exports."""
    if not isinstance(user, User):
        return sorted(team_ids)
    teams = Team.objects.filter(organization=organization, id__in=team_ids)
    return sorted(
        team.id
        for team in teams
        if UserAccessControl(
            user=user, team=team, organization_id=str(organization.id)
        ).check_access_level_for_resource("export", "editor")
    )
