"""DRF views for agentic_tests."""

import json
import asyncio
import threading
from collections.abc import AsyncIterator
from typing import Any

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

from products.agentic_tests.backend.logic.execution import execute_agentic_test
from products.agentic_tests.backend.logic.runner import AgentEvent, run_agent
from products.agentic_tests.backend.models import AgenticTest, AgenticTestRun

from .serializers import AgenticTestRunSerializer, AgenticTestSerializer


class AgenticTestViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    queryset = AgenticTest.objects.all()
    serializer_class = AgenticTestSerializer

    def safely_get_queryset(self, queryset: QuerySet[AgenticTest]) -> QuerySet[AgenticTest]:
        return queryset.filter(team_id=self.team_id).order_by("-created_at")

    def perform_create(self, serializer: serializers.BaseSerializer) -> None:
        serializer.save(
            team_id=self.team_id,
            created_by=self.request.user if self.request.user.is_authenticated else None,
        )

    @extend_schema(
        request=None,
        responses=AgenticTestRunSerializer,
        description="Trigger an immediate run of this agentic test (blocks until complete; for long runs prefer `stream`).",
    )
    @action(detail=True, methods=["post"])
    def run_now(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        test: AgenticTest = self.get_object()
        run = execute_agentic_test(test)
        return Response(AgenticTestRunSerializer(run).data, status=status.HTTP_202_ACCEPTED)

    @extend_schema(
        request=None,
        responses={200: None},
        description=(
            "Trigger a run and stream progress as Server-Sent Events. "
            "Each event is a JSON line with `type` and `data`. A terminal event with `type='final'` "
            "carries the persisted AgenticTestRun id (`run_id`) so the client can fetch the row."
        ),
    )
    @action(detail=True, methods=["post"])
    def stream(self, request: Request, *args: Any, **kwargs: Any) -> StreamingHttpResponse:
        test: AgenticTest = self.get_object()
        run = AgenticTestRun.objects.create(
            agentic_test=test,
            status=AgenticTestRun.Status.RUNNING,
        )

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
        test.save(update_fields=["status", "updated_at"])
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
        test.save(update_fields=["status", "updated_at"])
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
    """
    yield _sse("run_started", {"run_id": str(run.id), "agentic_test_id": str(test.id)})

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[AgentEvent | object] = asyncio.Queue()
    SENTINEL: object = object()

    def producer() -> None:
        try:
            for event in run_agent(prompt=test.prompt, target_url=test.target_url):
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
            yield _sse(item.type, {"step": item.step, **item.data})
            if item.type == "final":
                final = item.data
    finally:
        await sync_to_async(_persist_run_terminal, thread_sensitive=True)(
            run=run,
            test=test,
            result=final or {},
        )

    yield _sse("run_finished", {"run_id": str(run.id), "status": run.status})


def _persist_run_terminal(*, run: AgenticTestRun, test: AgenticTest, result: dict[str, Any]) -> None:
    """Write the final state of a streamed run, mirroring execute_agentic_test."""
    passed = bool(result.get("passed", False))
    output = result.get("output") or {}
    run.finished_at = timezone.now()
    run.duration_ms = int(output.get("duration_ms") or 0)
    run.output = output
    run.external_session_id = result.get("external_session_id", "") or ""
    run.screenshot_url = result.get("screenshot_url", "") or ""
    run.status = AgenticTestRun.Status.PASSED if passed else AgenticTestRun.Status.FAILED
    if not passed:
        run.error_message = (result.get("error") or "")[:5000]
    run.save()

    test.last_run_at = run.started_at
    test.save(update_fields=["last_run_at", "updated_at"])
