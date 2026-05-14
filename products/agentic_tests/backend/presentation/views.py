"""DRF views for agentic_tests."""

import json
import asyncio
import threading
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from products.tasks.backend.models import Task

from django.db.models import QuerySet
from django.http import StreamingHttpResponse
from django.utils import timezone

from asgiref.sync import sync_to_async
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.renderers import ServerSentEventRenderer

from products.agentic_tests.backend.logic.execution import queue_agentic_test_run, queue_agentic_test_runs
from products.agentic_tests.backend.logic.runner import AgentEvent, run_agent
from products.agentic_tests.backend.logic.scheduling import refresh_next_run_at
from products.agentic_tests.backend.models import AgenticTest, AgenticTestRun

from .serializers import (
    AgenticTestRunSerializer,
    AgenticTestSerializer,
    DetectFlowsRequestSerializer,
    DetectFlowsResponseSerializer,
)


class AgenticTestViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    queryset = AgenticTest.objects.all()
    serializer_class = AgenticTestSerializer

    def safely_get_queryset(self, queryset: QuerySet[AgenticTest]) -> QuerySet[AgenticTest]:
        return queryset.filter(team_id=self.team_id).order_by("-created_at")

    def perform_create(self, serializer: serializers.BaseSerializer) -> None:
        test = serializer.save(
            team_id=self.team_id,
            created_by=self.request.user if self.request.user.is_authenticated else None,
        )
        refresh_next_run_at(test)

    def perform_update(self, serializer: serializers.BaseSerializer) -> None:
        test = serializer.save()
        refresh_next_run_at(test)

    @extend_schema(
        methods=["GET"],
        request=None,
        responses={200: DetectFlowsResponseSerializer},
        description="Get the latest flow-detection task for this team, if any.",
    )
    @extend_schema(
        methods=["POST"],
        request=DetectFlowsRequestSerializer,
        responses={202: DetectFlowsResponseSerializer},
        description="Launch a sandboxed agent to analyze a GitHub repository and propose test flows.",
    )
    @extend_schema(
        methods=["DELETE"],
        request=None,
        responses={204: None},
        description="Dismiss the latest flow-detection task (soft-delete).",
    )
    @action(detail=False, methods=["get", "post", "delete"])
    def detect_flows(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        if request.method == "GET":
            return self._get_detect_flows_status()
        if request.method == "DELETE":
            return self._dismiss_detect_flows()
        return self._start_detect_flows(request)

    def _get_detect_flows_status(self) -> Response:
        task = self._get_latest_detect_flows_task()
        if task is None:
            return Response(None, status=status.HTTP_204_NO_CONTENT)

        run = task.runs.order_by("-created_at").first()
        if run is None:
            return Response(None, status=status.HTTP_204_NO_CONTENT)

        return Response(
            DetectFlowsResponseSerializer({"task_id": task.id, "task_run_id": run.id, "status": run.status}).data,
        )

    def _dismiss_detect_flows(self) -> Response:
        task = self._get_latest_detect_flows_task()
        if task is not None:
            task.soft_delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _get_latest_detect_flows_task(self) -> "Task | None":
        from products.tasks.backend.models import Task

        return (
            Task.objects.filter(
                team_id=self.team_id,
                origin_product=Task.OriginProduct.AGENTIC_TESTS,
                deleted=False,
            )
            .order_by("-created_at")
            .first()
        )

    def _start_detect_flows(self, request: Request) -> Response:
        serializer = DetectFlowsRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        from products.agentic_tests.backend.logic.detect_flows import launch_detect_flows_task

        task = launch_detect_flows_task(
            team=self.team,
            user=request.user,
            repository=serializer.validated_data["repository"],
            domain=serializer.validated_data["domain"],
        )
        task_run = task.runs.order_by("-created_at").first()
        return Response(
            DetectFlowsResponseSerializer({"task_id": task.id, "task_run_id": task_run.id if task_run else None}).data,
            status=status.HTTP_202_ACCEPTED,
        )

    @extend_schema(
        request=None,
        responses=AgenticTestRunSerializer,
        description="Trigger an immediate run of this agentic test (blocks until complete; for long runs prefer `stream`).",
    )
    @action(detail=True, methods=["post"])
    def run_now(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        test: AgenticTest = self.get_object()
        runs = queue_agentic_test_runs(test)
        return Response(
            AgenticTestRunSerializer(runs, many=True).data,
            status=status.HTTP_202_ACCEPTED,
        )

    @extend_schema(
        request=None,
        responses={200: None},
        description=(
            "Trigger a run and stream progress as Server-Sent Events. "
            "Each event is a JSON line with `type` and `data`. A terminal event with `type='final'` "
            "carries the persisted AgenticTestRun id (`run_id`) so the client can fetch the row."
        ),
    )
    @action(detail=True, methods=["post"], renderer_classes=[ServerSentEventRenderer])
    def stream(self, request: Request, *args: Any, **kwargs: Any) -> StreamingHttpResponse:
        test: AgenticTest = self.get_object()
        # If the test has multiple regions configured, fan out: stream the first region's
        # run inline, dispatch the rest as background celery runs. Each becomes its own
        # AgenticTestRun row tagged with its region.
        configured = [r for r in (test.regions or []) if r]
        primary_region = configured[0] if configured else ""
        run = AgenticTestRun.objects.create(
            agentic_test=test,
            status=AgenticTestRun.Status.RUNNING,
            source=AgenticTestRun.Source.MANUAL,
            region=primary_region,
        )
        # Fan out the additional regions via the same celery queue used by the schedule.
        for region in configured[1:]:
            queue_agentic_test_run(test, source=AgenticTestRun.Source.MANUAL, region=region)

        response = StreamingHttpResponse(
            _stream_run(run=run, test=test),
            content_type="text/event-stream",
        )
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        response["Connection"] = "keep-alive"
        return response

    @extend_schema(
        request=None,
        responses=AgenticTestSerializer,
        description="Mark a proposed or paused test as active.",
    )
    @action(detail=True, methods=["post"])
    def activate(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        test: AgenticTest = self.get_object()
        test.status = AgenticTest.Status.ACTIVE
        test.save(update_fields=["status", "updated_at"])
        refresh_next_run_at(test)
        return Response(self.get_serializer(test).data)

    @extend_schema(
        request=None,
        responses=AgenticTestSerializer,
        description="Mark a test as paused.",
    )
    @action(detail=True, methods=["post"])
    def pause(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        test: AgenticTest = self.get_object()
        test.status = AgenticTest.Status.PAUSED
        test.next_run_at = None
        test.save(update_fields=["status", "next_run_at", "updated_at"])
        return Response(self.get_serializer(test).data)

    @extend_schema(
        request=None,
        responses=AgenticTestSerializer,
        description="Reject a proposed test. The test is kept (status=rejected) so users can restore it later.",
    )
    @action(detail=True, methods=["post"])
    def reject(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        test: AgenticTest = self.get_object()
        test.status = AgenticTest.Status.REJECTED
        test.next_run_at = None
        test.save(update_fields=["status", "next_run_at", "updated_at"])
        return Response(self.get_serializer(test).data)


class AgenticTestRunViewSet(TeamAndOrgViewSetMixin, viewsets.ReadOnlyModelViewSet):
    scope_object = "INTERNAL"
    queryset = AgenticTestRun.objects.all()
    serializer_class = AgenticTestRunSerializer

    def _should_skip_parents_filter(self) -> bool:
        # AgenticTestRun has no direct `team` FK — it's reachable via agentic_test.team.
        # We filter via the parent test in `safely_get_queryset` instead.
        return True

    def safely_get_queryset(self, queryset: QuerySet[AgenticTestRun]) -> QuerySet[AgenticTestRun]:
        qs = queryset.filter(agentic_test__team_id=self.team_id)
        test_id = self.request.query_params.get("agentic_test")
        if test_id:
            qs = qs.filter(agentic_test_id=test_id)
        return qs.order_by("-started_at")


_SSE_KEEPALIVE = b": keepalive\n\n"
_SSE_KEEPALIVE_INTERVAL_S = 10.0


def _sse(event: str, data: dict[str, Any]) -> bytes:
    """Format a Server-Sent Events frame."""
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n".encode()


async def _stream_run(*, run: AgenticTestRun, test: AgenticTest) -> AsyncIterator[bytes]:
    """Async SSE generator. Bridges the sync `run_agent` via a producer thread.

    Why this shape: `run_agent` uses sync_playwright(), which can't run inside an
    asyncio event loop. We spawn a thread that consumes the sync generator and
    pushes events into an asyncio.Queue; this async generator awaits the queue
    and yields SSE frames. The async generator is what lets Django's ASGI handler
    (Granian) actually stream chunks to the client instead of collecting them.

    Every event is also captured into a local list and persisted onto the run row
    at the end so the Runs tab has a permanent record of what happened.
    """
    yield _sse("run_started", {"run_id": str(run.id), "agentic_test_id": str(test.id)})

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[AgentEvent | object] = asyncio.Queue()
    SENTINEL: object = object()

    def producer() -> None:
        try:
            for event in run_agent(
                prompt=test.prompt,
                target_url=test.target_url,
                regions=[run.region] if run.region else [],
                test_id=str(test.id),
                test_name=test.name,
                run_id=str(run.id),
            ):
                loop.call_soon_threadsafe(queue.put_nowait, event)
        except Exception as exc:  # noqa: BLE001 — surface crashes as a final event
            crash = AgentEvent(
                "final",
                {
                    "passed": False,
                    "error": f"Runner crashed: {exc}",
                    "output": {},
                    "external_session_id": "",
                    "screenshot_url": "",
                },
            )
            loop.call_soon_threadsafe(queue.put_nowait, crash)
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, SENTINEL)

    threading.Thread(target=producer, daemon=True).start()

    final: dict[str, Any] | None = None
    captured_events: list[dict[str, Any]] = []
    last_flush_at: float = 0.0
    eager_session_persisted: bool = False
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=_SSE_KEEPALIVE_INTERVAL_S)
            except TimeoutError:
                # No event for a while — emit a comment to keep the connection warm
                # and to force a flush through any intermediate buffer.
                yield _SSE_KEEPALIVE
                continue
            if item is SENTINEL:
                break
            assert isinstance(item, AgentEvent)
            captured_events.append({"type": item.type, "step": item.step, "data": item.data})
            yield _sse(item.type, {"step": item.step, **item.data})
            if item.type == "final":
                final = item.data
            # Persist the eagerly-paired session id the moment the runner publishes it,
            # so the UI shows "View replay →" within ~1s of run start (not at end).
            if not eager_session_persisted and item.type == "status":
                sid = item.data.get("posthog_session_id", "")
                if sid:
                    await sync_to_async(_flush_run_session_id, thread_sensitive=True)(
                        run_id=str(run.id), posthog_session_id=sid
                    )
                    eager_session_persisted = True
            # Periodically persist captured events to the run row so polling clients see
            # live progress and a page refresh doesn't lose the in-flight log stream.
            now = asyncio.get_event_loop().time()
            if now - last_flush_at > 1.5:
                await sync_to_async(_flush_run_log_entries, thread_sensitive=True)(
                    run_id=str(run.id), log_entries=list(captured_events)
                )
                last_flush_at = now
    finally:
        await sync_to_async(_persist_run_terminal, thread_sensitive=True)(
            run=run,
            test=test,
            result=final or {},
            log_entries=captured_events,
        )

    yield _sse("run_finished", {"run_id": str(run.id), "status": run.status})


def _flush_run_log_entries(*, run_id: str, log_entries: list[dict[str, Any]]) -> None:
    """Cheap incremental write — used during the run so the UI's polling loop sees progress."""
    AgenticTestRun.objects.filter(id=run_id).update(log_entries=log_entries)


def _flush_run_session_id(*, run_id: str, posthog_session_id: str) -> None:
    """Persist the eagerly-paired posthog session id as soon as the runner has it."""
    AgenticTestRun.objects.filter(id=run_id).update(posthog_session_id=posthog_session_id)


def _persist_run_terminal(
    *,
    run: AgenticTestRun,
    test: AgenticTest,
    result: dict[str, Any],
    log_entries: list[dict[str, Any]],
) -> None:
    """Write the final state of a streamed run. Mirrors `execute_agentic_test_run` so
    both the celery and SSE paths converge on the same persisted row shape."""
    from products.agentic_tests.backend.logic.execution import _lookup_posthog_session_id

    passed = bool(result.get("passed", False))
    output = result.get("output") or {}
    run.finished_at = timezone.now()
    run.duration_ms = int(output.get("duration_ms") or 0)
    run.output = output
    run.external_session_id = result.get("external_session_id", "") or ""
    run.screenshot_url = result.get("screenshot_url", "") or ""
    run.region = result.get("region", "") or ""
    run.log_entries = log_entries
    # Eager pairing first (runner.page.evaluate). Fall back to CH lookup only if missing.
    eager_session_id = result.get("posthog_session_id", "") or ""
    if eager_session_id:
        run.posthog_session_id = eager_session_id
    else:
        run.posthog_session_id = _lookup_posthog_session_id(team_id=test.team_id, run=run)
    if not run.posthog_session_id:
        from products.agentic_tests.backend.tasks.tasks import pair_posthog_session_for_run

        pair_posthog_session_for_run.apply_async(args=[str(run.id)], countdown=15)
    run.status = AgenticTestRun.Status.PASSED if passed else AgenticTestRun.Status.FAILED
    if not passed:
        run.error_message = (result.get("error") or "")[:5000]
    run.save()

    test.last_run_at = run.started_at
    test.save(update_fields=["last_run_at", "updated_at"])
