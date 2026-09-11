"""Staff/dev-only debug surface for the lazy precompute store.

Answers "what precompute do we have for this team?" across every product that
uses the lazy-computation framework (web analytics, marketing analytics,
experiments): which query hashes are stored, which buckets each covers, how
long until each bucket's TTL expires, and — where recoverable — the
originating query (with filters) each hash serves. Also allows invalidating a
team's stored precompute (marking READY jobs stale) so the next read
recomputes, e.g. after a source resync changed the underlying data.
Conceptually a sibling of the "Debug ClickHouse queries" page.

The `PreaggregationJob` table stores only the SHA-256 of the normalized insert
AST, not the query itself. The originating query is recovered by correlation:
every insert statement embeds its `job_id` literal and its `log_comment`
carries the runner's full query JSON plus `query_type`, so a `system.query_log`
lookup over recent inserts labels each hash. Hashes whose last insert predates
the query_log lookback stay unlabeled rather than guessed.
"""

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from django.conf import settings
from django.db.models import Q

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from loginas.utils import is_impersonated_session
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.clickhouse.client import sync_execute
from posthog.cloud_utils import is_cloud

from products.analytics_platform.backend.models.preaggregation_job import PreaggregationJob

# Dead (expired/failed) jobs older than this are not shown. Unexpired jobs are
# always shown regardless of age, so long-TTL stores (e.g. the 90-day
# dimensional buckets) never silently drop out of the view.
JOB_LOOKBACK_DAYS = 35

# How far back to search `system.query_log` for the insert that produced a
# hash's most recent job. Bounded by query_log retention and scan cost; hashes
# whose newest insert is older than this simply come back unlabeled.
QUERY_LOG_LOOKBACK_DAYS = 3

# Per-response caps: hash groups are the unit of attention, buckets per group
# cover a full warm window plus slack.
MAX_GROUPS_DEFAULT = 50
MAX_GROUPS = 200
MAX_BUCKETS_PER_GROUP = 70


class PrecomputeDebugBucketSerializer(serializers.Serializer):
    time_range_start = serializers.DateTimeField(help_text="Start of the bucket's time window (inclusive).")
    time_range_end = serializers.DateTimeField(help_text="End of the bucket's time window (exclusive).")
    status = serializers.ChoiceField(
        choices=PreaggregationJob.Status.choices, help_text="Lifecycle state of this bucket's job."
    )
    computed_at = serializers.DateTimeField(
        allow_null=True, help_text="When the bucket's data was last computed; null if never computed."
    )
    expires_at = serializers.DateTimeField(
        allow_null=True, help_text="When the bucket's data expires in ClickHouse; null if no TTL recorded."
    )
    ttl_seconds_remaining = serializers.IntegerField(
        allow_null=True,
        help_text="Seconds until the bucket expires; negative when already expired, null if no TTL recorded.",
    )


class PrecomputeDebugSampleSerializer(serializers.Serializer):
    query_type = serializers.CharField(
        allow_null=True, help_text="query_type tag of the insert that built this hash (identifies the query family)."
    )
    trigger = serializers.CharField(
        allow_null=True,
        help_text="Trigger tag of the insert: a warmer trigger name, or empty for a user-initiated read.",
    )
    query_json = serializers.CharField(
        allow_null=True,
        help_text=(
            "Originating query as JSON (from the insert's log_comment) including date range and property "
            "filters — shows which dashboard queries this hash serves."
        ),
    )
    last_insert_at = serializers.DateTimeField(
        allow_null=True, help_text="When the sampled insert for this hash finished."
    )


class PrecomputeDebugGroupSerializer(serializers.Serializer):
    query_hash = serializers.CharField(help_text="SHA-256 of the normalized insert query this group covers.")
    job_count = serializers.IntegerField(help_text="Number of bucket jobs stored for this hash (within caps).")
    status_counts = serializers.DictField(
        child=serializers.IntegerField(), help_text="Job count per lifecycle status for this hash."
    )
    earliest_start = serializers.DateTimeField(help_text="Start of the earliest bucket stored for this hash.")
    latest_end = serializers.DateTimeField(help_text="End of the latest bucket stored for this hash.")
    last_computed_at = serializers.DateTimeField(
        allow_null=True, help_text="Most recent computed_at across the hash's buckets."
    )
    sample = PrecomputeDebugSampleSerializer(
        allow_null=True,
        help_text="Originating-query sample recovered from query_log; null when no recent insert was found.",
    )
    buckets = PrecomputeDebugBucketSerializer(
        many=True, help_text=f"Most recent buckets for this hash (capped at {MAX_BUCKETS_PER_GROUP})."
    )


class PrecomputeDebugResponseSerializer(serializers.Serializer):
    generated_at = serializers.DateTimeField(help_text="When this snapshot was generated.")
    job_lookback_days = serializers.IntegerField(
        help_text="Expired/failed jobs older than this many days are omitted; unexpired jobs are always shown."
    )
    query_log_lookback_days = serializers.IntegerField(
        help_text="How far back query_log was searched to label hashes with their originating query."
    )
    total_hashes = serializers.IntegerField(help_text="Distinct hashes stored for the team within the job lookback.")
    groups = PrecomputeDebugGroupSerializer(many=True, help_text="Per-hash groups, most recently computed first.")


class PrecomputeInvalidateRequestSerializer(serializers.Serializer):
    query_hash = serializers.CharField(
        required=False,
        allow_null=True,
        default=None,
        max_length=64,
        help_text="Only invalidate jobs for this query hash. Omit to invalidate every hash stored for the team.",
    )


class PrecomputeInvalidateResponseSerializer(serializers.Serializer):
    updated_count = serializers.IntegerField(help_text="Number of READY jobs marked stale.")
    query_hash = serializers.CharField(
        allow_null=True, help_text="The hash that was invalidated, or null when all hashes were targeted."
    )


def _fetch_samples_from_query_log(team_id: int, job_ids_by_hash: dict[str, str]) -> dict[str, dict[str, Any]]:
    """Label hashes with the insert that produced their most recent job.

    Matches the `job_id` literal embedded in each insert statement. Best-effort:
    any failure returns {} so the debug page still renders the Postgres side.
    """
    if not job_ids_by_hash:
        return {}
    hashes = list(job_ids_by_hash.keys())
    job_ids = [job_ids_by_hash[h] for h in hashes]
    try:
        rows = sync_execute(
            """
            SELECT
                multiSearchFirstIndex(query, %(job_ids)s) AS idx,
                argMax(JSONExtractString(log_comment, 'query_type'), event_time) AS query_type,
                argMax(JSONExtractString(log_comment, 'trigger'), event_time) AS trigger,
                argMax(JSONExtractRaw(log_comment, 'query'), event_time) AS query_json,
                max(event_time) AS last_insert_at
            FROM clusterAllReplicas(%(cluster)s, system, query_log)
            WHERE event_time > now() - INTERVAL %(lookback_days)s DAY
              AND query_kind = 'Insert'
              AND type = 'QueryFinish'
              AND is_initial_query = 1
              AND JSONExtractInt(log_comment, 'team_id') = %(team_id)s
              AND multiSearchAny(query, %(job_ids)s)
            GROUP BY idx
            """,
            {
                "cluster": settings.CLICKHOUSE_CLUSTER,
                "lookback_days": QUERY_LOG_LOOKBACK_DAYS,
                "team_id": team_id,
                "job_ids": job_ids,
            },
        )
    except Exception:
        return {}

    samples: dict[str, dict[str, Any]] = {}
    for idx, query_type, trigger, query_json, last_insert_at in rows:
        if idx < 1 or idx > len(hashes):
            continue
        samples[hashes[idx - 1]] = {
            "query_type": query_type or None,
            "trigger": trigger,
            "query_json": query_json or None,
            "last_insert_at": last_insert_at,
        }
    return samples


class PrecomputeDebugViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    # `scope_object = "INTERNAL"` blocks a staff user's full-access (`*`) PAT via the
    # wildcard short-circuit in `APIScopePermission.has_permission`. Each action pins a
    # `query_performance` scope — OAuth-hidden, PAT-grantable (see OAUTH_HIDDEN_SCOPE_OBJECTS)
    # so staff automation can reach it; the browser uses session auth, which bypasses scope
    # checks. `_check_debug_access` gates every action in every case.
    scope_object = "INTERNAL"

    def _check_debug_access(self, request: Request) -> Response | None:
        if request.user.is_staff or settings.DEBUG or is_impersonated_session(request) or not is_cloud():
            return None
        return Response({"detail": "Staff access required."}, status=status.HTTP_403_FORBIDDEN)

    @extend_schema(
        operation_id="precompute_debug_state",
        summary="Inspect stored lazy-precompute state (staff only)",
        description=(
            "Staff/dev-only debug view of the team's lazy precompute store: which query hashes are stored, "
            "which buckets each covers, per-bucket TTL, and — where recoverable from query_log — the "
            "originating query (with filters) each hash serves."
        ),
        parameters=[
            OpenApiParameter(
                name="limit",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=False,
                default=MAX_GROUPS_DEFAULT,
                description=f"Maximum number of hash groups to return (1–{MAX_GROUPS}).",
            ),
        ],
        responses={200: OpenApiResponse(response=PrecomputeDebugResponseSerializer)},
    )
    @action(detail=False, methods=["get"], url_path="state", required_scopes=["query_performance:read"])
    def state(self, request: Request, **kwargs: Any) -> Response:
        denied = self._check_debug_access(request)
        if denied is not None:
            return denied

        try:
            limit = max(1, min(int(request.query_params.get("limit", MAX_GROUPS_DEFAULT)), MAX_GROUPS))
        except ValueError:
            limit = MAX_GROUPS_DEFAULT

        now = datetime.now(UTC)
        jobs = (
            PreaggregationJob.objects.filter(
                Q(expires_at__gte=now) | Q(created_at__gte=now - timedelta(days=JOB_LOOKBACK_DAYS)),
                team_id=self.team.pk,
            )
            .order_by("-time_range_end")
            .values("query_hash", "time_range_start", "time_range_end", "status", "computed_at", "expires_at")
        )

        grouped: dict[str, list[Any]] = defaultdict(list)
        for job in jobs.iterator(chunk_size=2000):
            grouped[job["query_hash"]].append(job)

        def group_sort_key(item: tuple[str, list[Any]]) -> datetime:
            computed = [j["computed_at"] for j in item[1] if j["computed_at"] is not None]
            return max(computed) if computed else datetime.min.replace(tzinfo=UTC)

        ordered = sorted(grouped.items(), key=group_sort_key, reverse=True)[:limit]

        groups: list[dict[str, Any]] = []
        job_ids_by_hash: dict[str, str] = {}
        for query_hash, hash_jobs in ordered:
            status_counts: dict[str, int] = defaultdict(int)
            for j in hash_jobs:
                status_counts[j["status"]] += 1
            computed = [j["computed_at"] for j in hash_jobs if j["computed_at"] is not None]
            groups.append(
                {
                    "query_hash": query_hash,
                    "job_count": len(hash_jobs),
                    "status_counts": dict(status_counts),
                    "earliest_start": min(j["time_range_start"] for j in hash_jobs),
                    "latest_end": max(j["time_range_end"] for j in hash_jobs),
                    "last_computed_at": max(computed) if computed else None,
                    "sample": None,
                    "buckets": [
                        {
                            "time_range_start": j["time_range_start"],
                            "time_range_end": j["time_range_end"],
                            "status": j["status"],
                            "computed_at": j["computed_at"],
                            "expires_at": j["expires_at"],
                            "ttl_seconds_remaining": (
                                int((j["expires_at"] - now).total_seconds()) if j["expires_at"] else None
                            ),
                        }
                        for j in hash_jobs[:MAX_BUCKETS_PER_GROUP]
                    ],
                }
            )

        # Correlate each hash with its most recent job's insert in query_log. Jobs
        # need an id for the match; re-query only the ids for the sampled jobs.
        sampled_hashes = [g["query_hash"] for g in groups]
        if sampled_hashes:
            id_rows = (
                PreaggregationJob.objects.filter(
                    team_id=self.team.pk,
                    query_hash__in=sampled_hashes,
                    computed_at__isnull=False,
                )
                .order_by("query_hash", "-computed_at")
                .distinct("query_hash")
                .values_list("query_hash", "id")
            )
            job_ids_by_hash = {h: str(job_id) for h, job_id in id_rows}
        samples = _fetch_samples_from_query_log(self.team.pk, job_ids_by_hash)
        for group in groups:
            group["sample"] = samples.get(group["query_hash"])

        payload = {
            "generated_at": now,
            "job_lookback_days": JOB_LOOKBACK_DAYS,
            "query_log_lookback_days": QUERY_LOG_LOOKBACK_DAYS,
            "total_hashes": len(grouped),
            "groups": groups,
        }
        return Response(PrecomputeDebugResponseSerializer(payload).data)

    @extend_schema(
        operation_id="precompute_debug_invalidate",
        summary="Invalidate stored precompute for this team (staff only)",
        description=(
            "Marks the team's READY precompute jobs stale so the next read recomputes them, e.g. after a "
            "source resync changed the underlying data. Optionally scoped to a single query hash. PENDING "
            "jobs are left alone: anything in flight is already computing against current data."
        ),
        request=PrecomputeInvalidateRequestSerializer,
        responses={200: OpenApiResponse(response=PrecomputeInvalidateResponseSerializer)},
    )
    @action(detail=False, methods=["post"], url_path="invalidate", required_scopes=["query_performance:write"])
    def invalidate(self, request: Request, **kwargs: Any) -> Response:
        denied = self._check_debug_access(request)
        if denied is not None:
            return denied

        request_serializer = PrecomputeInvalidateRequestSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        query_hash = request_serializer.validated_data["query_hash"]

        jobs = PreaggregationJob.objects.filter(team_id=self.team.pk, status=PreaggregationJob.Status.READY)
        if query_hash:
            jobs = jobs.filter(query_hash=query_hash)
        updated_count = jobs.update(status=PreaggregationJob.Status.STALE)

        payload = {"updated_count": updated_count, "query_hash": query_hash}
        return Response(PrecomputeInvalidateResponseSerializer(payload).data)
