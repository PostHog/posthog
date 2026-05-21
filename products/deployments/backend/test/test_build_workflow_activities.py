from __future__ import annotations

from uuid import UUID

import pytest
from unittest.mock import AsyncMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.deployments.backend.domain.status import Status
from products.deployments.backend.domain.trigger import ErrorStep
from products.deployments.backend.temporal.activities import (
    MarkFailedInput,
    MarkReadyInput,
    StepInput,
    build_site,
    clone_repo,
    initialize_build,
    install_dependencies,
    mark_failed,
    mark_ready,
    start_building,
    upload_artifacts,
)

DEPLOYMENT_ID = UUID("00000000-0000-7000-8000-000000000001")
STEP = StepInput(
    deployment_id=DEPLOYMENT_ID,
    cloudflare_project_name="hogdev-1-myapp",
    repo_url="https://github.com/example/repo",
    branch="main",
    commit_sha="abc123",
    output_dir="dist",
    github_access_token=None,
    build_command=None,
)


class TestBuildActivities(SimpleTestCase):
    @pytest.mark.asyncio
    async def test_initialize_build_posts_initializing_transition(self) -> None:
        with (
            patch("products.deployments.backend.temporal.activities.post_transition", new=AsyncMock()) as t,
            patch("products.deployments.backend.temporal.activities.post_event", new=AsyncMock()) as e,
        ):
            await initialize_build(STEP)

        t.assert_awaited_once_with(deployment_id=DEPLOYMENT_ID, status=Status.INITIALIZING)
        e.assert_awaited_once()
        # Event payload mirrors the transition.
        assert e.await_args is not None
        kwargs = e.await_args.kwargs
        self.assertEqual(kwargs["deployment_id"], DEPLOYMENT_ID)
        self.assertEqual(kwargs["event_type"], "status_changed")
        self.assertEqual(kwargs["payload"], {"to": "initializing"})

    @pytest.mark.asyncio
    async def test_start_building_posts_building_transition(self) -> None:
        with (
            patch("products.deployments.backend.temporal.activities.post_transition", new=AsyncMock()) as t,
            patch("products.deployments.backend.temporal.activities.post_event", new=AsyncMock()),
        ):
            await start_building(STEP)
        t.assert_awaited_once_with(deployment_id=DEPLOYMENT_ID, status=Status.BUILDING)

    @pytest.mark.asyncio
    async def test_mark_ready_propagates_deployment_url(self) -> None:
        payload = MarkReadyInput(
            deployment_id=DEPLOYMENT_ID,
            deployment_url="https://hogdev-1-myapp.pages.dev",
            cloudflare_deployment_id="d1",
        )
        with (
            patch("products.deployments.backend.temporal.activities.post_transition", new=AsyncMock()) as t,
            patch("products.deployments.backend.temporal.activities.post_event", new=AsyncMock()),
        ):
            await mark_ready(payload)
        t.assert_awaited_once_with(
            deployment_id=DEPLOYMENT_ID,
            status=Status.READY,
            deployment_url="https://hogdev-1-myapp.pages.dev",
            cloudflare_deployment_id="d1",
        )

    @pytest.mark.asyncio
    async def test_mark_failed_propagates_error_step(self) -> None:
        payload = MarkFailedInput(deployment_id=DEPLOYMENT_ID, error_message="kaboom", error_step=ErrorStep.BUILD)
        with (
            patch("products.deployments.backend.temporal.activities.post_transition", new=AsyncMock()) as t,
            patch("products.deployments.backend.temporal.activities.post_event", new=AsyncMock()) as e,
        ):
            await mark_failed(payload)
        t.assert_awaited_once_with(
            deployment_id=DEPLOYMENT_ID,
            status=Status.ERROR,
            error_message="kaboom",
            error_step=ErrorStep.BUILD,
        )
        # Event payload includes the error step + message for the timeline.
        assert e.await_args is not None
        kwargs = e.await_args.kwargs
        self.assertEqual(kwargs["payload"]["error_step"], "build")
        self.assertEqual(kwargs["payload"]["error_message"], "kaboom")

    @parameterized.expand(
        [
            ("clone_repo", clone_repo),
            ("install_dependencies", install_dependencies),
            ("build_site", build_site),
        ]
    )
    @pytest.mark.asyncio
    async def test_build_step_stub_only_emits_events(self, _name: str, activity) -> None:
        # The build-step stubs don't post transitions — those are the
        # responsibility of initialize_build / start_building / mark_*.
        # Each stub only emits events for the timeline.
        with (
            patch("products.deployments.backend.temporal.activities.post_transition", new=AsyncMock()) as t,
            patch("products.deployments.backend.temporal.activities.post_event", new=AsyncMock()) as e,
        ):
            await activity(STEP)
        t.assert_not_awaited()
        self.assertGreaterEqual(e.await_count, 1)

    @pytest.mark.asyncio
    async def test_upload_artifacts_returns_synthetic_pages_url(self) -> None:
        with (
            patch("products.deployments.backend.temporal.activities.post_transition", new=AsyncMock()),
            patch("products.deployments.backend.temporal.activities.post_event", new=AsyncMock()),
        ):
            url = await upload_artifacts(STEP)
        # Until the hogland-backed real upload lands, this is a known
        # placeholder so the workflow can complete end-to-end. The
        # placeholder shape mirrors what CF would return.
        self.assertEqual(url, "https://hogdev-1-myapp.pages.dev")
