"""Per-case seeder for the error-tracking sandboxed evals.

Owns the entire error-tracking surface for a per-case team:

  * Wipes any pre-existing ``ErrorTrackingIssue`` rows so the Hedgebox
    demo seed (which writes events through Kafka and never lands in the
    sandboxed-eval ClickHouse) can't leave stale, empty issues lying
    around to confuse the agent.
  * Creates three deterministic ``ErrorTrackingIssue`` PSQL rows with
    fresh UUIDs and matching ``ErrorTrackingIssueFingerprintV2`` rows.
  * Writes the matching ``$exception`` events directly to ClickHouse so
    concurrent setup hooks don't depend on the process-global ``settings.TEST``
    value used by ``ClickhouseProducer``. That makes the seed self-contained —
    no Kafka consumer, no fingerprint-override materialized view, no implicit
    dependency on the demo matrix.

Returned dict is merged into the task output under ``seed`` by
``base.py:task()`` so scorers reach it via ``output["seed"]``.
"""

from __future__ import annotations

import json
import uuid
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from posthog.clickhouse.client import sync_execute
from posthog.models import Team
from posthog.models.event.sql import INSERT_EVENT_SQL
from posthog.models.utils import uuid7

from products.error_tracking.backend.models import ErrorTrackingIssue, ErrorTrackingIssueFingerprintV2
from products.tasks.backend.services.custom_prompt_internals import CustomPromptSandboxContext

logger = logging.getLogger(__name__)


__all__ = ["EVAL_ISSUE_NAMES", "seed_error_tracking_issues"]


# Distinct-id pool used for the seeded ``$exception`` events. Synthetic so
# the seeder doesn't need to touch ``PersonDistinctId`` (which would force a
# personhog round-trip) — the query runner counts users by ``person_id``,
# which we derive deterministically below.
_EVAL_DISTINCT_IDS: tuple[str, ...] = (
    "eval-user-1",
    "eval-user-2",
    "eval-user-3",
    "eval-user-4",
)
# Stable namespace so the same distinct_id always resolves to the same
# synthetic person_id across cases. Keeps ``users`` aggregations realistic.
_EVAL_PERSON_NAMESPACE = uuid.UUID("3f7c8b1e-2d3a-4f5b-8c7d-9e0f1a2b3c4d")
_ZERO_CLICKHOUSE_TIMESTAMP = "1970-01-01 00:00:00.000000"


def _person_id_for(distinct_id: str) -> str:
    return str(uuid.uuid5(_EVAL_PERSON_NAMESPACE, distinct_id))


# Issue specs. Names are the strings scorers match against via
# ``expected.target_issue.name`` (case-insensitive substring against the
# ``lookup_issues`` entries returned below). The exception ``type``/``value``
# strings are what the agent's ``searchQuery`` can actually find — those
# search the CH event-level columns ``$exception_types`` / ``$exception_values``
# / ``$exception_sources`` / ``$exception_functions``, not the PSQL
# ``ErrorTrackingIssue.name`` field.
_ISSUE_SPECS: tuple[dict[str, Any], ...] = (
    {
        "name": "Checkout API timeout",
        "fingerprint": "eval-checkout-api-timeout-v1",
        "type": "TimeoutError",
        "value": "Request timed out while creating checkout session",
        "url": "https://app.hedgebox.test/app/files",
        "function": "submitPayment",
        "source": "https://app.hedgebox.test/static/js/checkout.js",
        "days_ago": (2, 5, 11, 18),
    },
    {
        "name": "File preview render failure",
        "fingerprint": "eval-file-preview-render-failure-v1",
        "type": "RenderError",
        "value": "Failed to render PDF preview",
        "url": "https://app.hedgebox.test/app/files/preview/file-abc123",
        "function": "renderPdfPreview",
        "source": "https://app.hedgebox.test/static/js/file-preview.js",
        "days_ago": (1, 4, 9),
    },
    {
        "name": "Team invite rejected",
        "fingerprint": "eval-team-invite-rejected-v1",
        "type": "TypeError",
        "value": "Cannot read properties of undefined (reading 'email')",
        "url": "https://app.hedgebox.test/settings/team",
        "function": "submitInvite",
        "source": "https://app.hedgebox.test/static/js/team-settings.js",
        "days_ago": (3, 7),
    },
)

EVAL_ISSUE_NAMES: tuple[str, ...] = tuple(spec["name"] for spec in _ISSUE_SPECS)


def _build_exception_properties(spec: dict[str, Any], issue_id: str) -> dict[str, Any]:
    """Construct the ``$exception`` event payload for one occurrence.

    Mirrors the shape Hedgebox's demo seed writes (see
    ``posthog/demo/products/hedgebox/matrix.py:_set_up_error_tracking_demo_data``)
    so the query runner's frame-extraction (``innermost_frame_attribute``)
    and the events tool's ``$exception_list`` rendering both work. Stack
    frames are inlined as ``resolved=True``; we deliberately skip the
    ``ErrorTrackingStackFrame`` PSQL rows since the agent only needs the
    top frame surfaced by ``query-error-tracking-issue``.
    """
    frame: dict[str, Any] = {
        "in_app": True,
        "resolved": True,
        "resolved_name": spec["function"],
        "mangled_name": spec["function"],
        "source": spec["source"],
        "lang": "javascript",
        "line": 42,
        "column": 7,
    }
    return {
        "$lib": "web",
        "$lib_version": "1.298.0",
        "$current_url": spec["url"],
        "$host": "app.hedgebox.test",
        "$pathname": spec["url"].split("hedgebox.test", 1)[-1] or "/",
        "$session_id": str(uuid.uuid4()),
        "$exception_level": "error",
        "$exception_handled": False,
        "$exception_issue_id": issue_id,
        "$exception_fingerprint": spec["fingerprint"],
        "$exception_proposed_fingerprint": spec["fingerprint"],
        "$exception_fingerprint_record": [{"type": "manual"}],
        "$exception_types": [spec["type"]],
        "$exception_values": [spec["value"]],
        "$exception_sources": [spec["source"]],
        "$exception_functions": [spec["function"]],
        "$exception_list": [
            {
                "type": spec["type"],
                "value": spec["value"],
                "mechanism": {"handled": False, "synthetic": False},
                "stacktrace": {"type": "resolved", "frames": [frame]},
            }
        ],
    }


def _insert_exception_event(
    *,
    team: Team,
    distinct_id: str,
    timestamp: datetime,
    properties: dict[str, Any],
) -> None:
    timestamp_utc = timestamp.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M:%S.%f")
    sync_execute(
        INSERT_EVENT_SQL(),
        {
            "uuid": str(uuid.uuid4()),
            "event": "$exception",
            "properties": json.dumps(properties),
            "timestamp": timestamp_utc,
            "team_id": team.id,
            "distinct_id": distinct_id,
            "elements_chain": "",
            "created_at": timestamp_utc,
            "person_id": _person_id_for(distinct_id),
            "person_properties": "{}",
            "person_created_at": _ZERO_CLICKHOUSE_TIMESTAMP,
            "group0_properties": "{}",
            "group1_properties": "{}",
            "group2_properties": "{}",
            "group3_properties": "{}",
            "group4_properties": "{}",
            "group0_created_at": _ZERO_CLICKHOUSE_TIMESTAMP,
            "group1_created_at": _ZERO_CLICKHOUSE_TIMESTAMP,
            "group2_created_at": _ZERO_CLICKHOUSE_TIMESTAMP,
            "group3_created_at": _ZERO_CLICKHOUSE_TIMESTAMP,
            "group4_created_at": _ZERO_CLICKHOUSE_TIMESTAMP,
            "person_mode": "full",
        },
    )


def seed_error_tracking_issues(context: CustomPromptSandboxContext) -> dict[str, Any]:
    """Seed three deterministic error-tracking issues + events on the per-case team.

    Synchronous — runs in a worker thread via ``asyncio.to_thread`` from
    ``base.py:task()``. Returns
    ``{"lookup_issues": [{"id": <uuid_str>, "name": <name>}, ...]}`` so
    deterministic scorers can resolve a target name back to the concrete
    UUID the agent should have passed as ``issueId``.
    """
    team = Team.objects.get(id=context.team_id)
    # Cascade kills any matching ``ErrorTrackingIssueFingerprintV2`` rows.
    # Hedgebox's demo seed creates rows here whose CH events never land in
    # the sandboxed eval environment — wiping them keeps the issues-list
    # response deterministic and free of confusing empty duplicates.
    ErrorTrackingIssue.objects.filter(team=team).delete()

    now = datetime.now(tz=UTC)
    lookup: list[dict[str, str]] = []

    for spec in _ISSUE_SPECS:
        issue_id = str(uuid7())
        ErrorTrackingIssue.objects.create(
            id=issue_id,
            team=team,
            name=spec["name"],
            status=ErrorTrackingIssue.Status.ACTIVE,
        )
        ErrorTrackingIssueFingerprintV2.objects.create(
            team=team,
            issue_id=issue_id,
            fingerprint=spec["fingerprint"],
        )

        for index, days_ago in enumerate(spec["days_ago"]):
            distinct_id = _EVAL_DISTINCT_IDS[index % len(_EVAL_DISTINCT_IDS)]
            timestamp = now - timedelta(days=days_ago, hours=index % 5)
            _insert_exception_event(
                team=team,
                distinct_id=distinct_id,
                timestamp=timestamp,
                properties=_build_exception_properties(spec, issue_id),
            )

        lookup.append({"id": issue_id, "name": spec["name"]})

    logger.info(
        "Seeded %d error-tracking issues + events for team_id=%s",
        len(lookup),
        context.team_id,
    )
    return {"lookup_issues": lookup}
