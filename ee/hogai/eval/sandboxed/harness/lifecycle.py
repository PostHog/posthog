from __future__ import annotations

import time
import atexit
import asyncio
import logging
from collections.abc import Sequence
from contextlib import AsyncExitStack, ExitStack

from unittest.mock import patch

from django.conf import settings
from django.test import override_settings

import posthoganalytics
from posthoganalytics import Posthog

from posthog.ph_client import get_client

from .cli import DEFAULT_DEMO_COPY_CONCURRENCY, HarnessOptions
from .context import EvalContext
from .demo_data import SandboxedDemoData, ensure_demo_ready
from .discovery import EvalSuite, discover_suites
from .django_env import EvalDatabase
from .env_preflight import validate_eval_env
from .live_server import EvalLiveServer
from .ports import DJANGO_LIVE_PORT
from .providers import build_provider
from .reporting import ProgressReporter, SuiteRunResult
from .services import (
    build_local_skills,
    ensure_personhog_binaries,
    start_llm_gateway,
    start_mcp_server,
    start_personhog,
    stop_all_subprocesses,
)
from .temporal_env import (
    TemporalWorkerThread,
    start_temporal_env,
    temporal_client_target,
    temporal_task_queue,
    terminate_stale_workflows,
)

logger = logging.getLogger(__name__)


class SandboxedEvalHarness:
    """Boots the shared eval infrastructure once, then runs every selected suite concurrently.

    Two phases. The sync bootstrap runs before any event loop exists, because
    Django's async-safety guard rejects sync ORM calls from an async context and
    most of the setup is ORM-heavy. The async phase owns Temporal, the suites,
    and the single global sandbox semaphore that bounds total load.
    """

    def __init__(self, options: HarnessOptions) -> None:
        self.options = options
        self.provider = build_provider(
            options.provider,
            keep_containers=options.keep_sandbox_containers,
            rebuild_image=options.rebuild_sandbox_image,
        )
        self._stack = ExitStack()
        self._database: EvalDatabase | None = None
        self._live_server: EvalLiveServer | None = None
        self._posthog_client: Posthog | None = None
        self._demo_data: SandboxedDemoData | None = None

    def run(self) -> int:
        # Discover before anything is provisioned: a typo'd selector should cost a
        # module import, not a database build and a Hedgebox seed.
        suites = discover_suites(self.options.selectors)

        if self.options.list_only:
            for suite in suites:
                print(suite.id)  # noqa: T201
            return 0

        validate_eval_env()
        self.provider.preflight()
        ensure_personhog_binaries()
        try:
            self._bootstrap()
            return asyncio.run(self._run_suites(suites))
        except KeyboardInterrupt:
            logger.warning("Interrupted, tearing down")
            return 130
        finally:
            self._stack.close()

    def _bootstrap(self) -> None:
        """Stand up everything the suites share. Teardown is registered in reverse on the stack."""
        # Belt and braces for the SIGINT / SIGTERM paths, where the ExitStack never unwinds.
        atexit.register(stop_all_subprocesses)
        atexit.register(self.provider.cleanup)

        database = EvalDatabase(keepdb=not self.options.create_db)
        database.setup()
        self._stack.callback(database.teardown)
        self._database = database

        # Bring personhog up before the live server and demo seeding: those bootstrap
        # reads go through the router, and a dead router would poison personhog's 30s
        # negative group-types cache for the rest of the run.
        self._stack.callback(start_personhog())

        live_server = EvalLiveServer(DJANGO_LIVE_PORT)
        self._stack.callback(live_server.stop)
        self._live_server = live_server

        self._stack.callback(start_llm_gateway(live_server.url))
        self._stack.callback(start_mcp_server(live_server.url))

        # Modal sandboxes live off-host, so the three services above have to be
        # publicly reachable before any settings pointing at them are computed.
        self.provider.start(self._stack)

        # DockerSandbox bind-mounts the built skills; ModalSandbox bakes them into
        # the image it builds from the local context, so it wants no host path.
        build_local_skills(set_bind_mount_env=self.options.provider == "docker")

        self._posthog_client = get_client("US")
        if self._posthog_client is not None:
            self._stack.callback(self._posthog_client.shutdown)

        self._demo_data = ensure_demo_ready(
            blocker=database.blocker,
            agent_model=self.options.agent_model,
            sandbox_timeout_seconds=self.provider.sandbox_timeout_seconds(self.options.per_case_timeout_seconds),
        )

    async def _run_suites(self, suites: Sequence[EvalSuite]) -> int:
        async with AsyncExitStack() as stack:
            temporal_env = await start_temporal_env()
            stack.push_async_callback(temporal_env.shutdown)
            temporal_host, temporal_port = temporal_client_target(temporal_env)

            stack.enter_context(
                override_settings(
                    DEBUG=True,  # Required for sandbox URL validation to allow http://localhost
                    # The sandbox reaches the Django live server with a non-loopback
                    # Host header (host.docker.internal, or the ngrok domain); allow it
                    # (test-only) so the agent's event-ingest stream isn't rejected with
                    # an invalid-host 400.
                    ALLOWED_HOSTS=["*"],
                    TEMPORAL_HOST=temporal_host,
                    TEMPORAL_PORT=temporal_port,
                    TEMPORAL_NAMESPACE=settings.TEMPORAL_NAMESPACE,
                    TEMPORAL_CLIENT_CERT=None,
                    TEMPORAL_CLIENT_KEY=None,
                    # Keep eval workflows off any dev worker already polling the normal tasks queue.
                    TASKS_TASK_QUEUE=temporal_task_queue(),
                    **self.provider.settings_overrides(),
                )
            )
            stack.enter_context(patch.object(posthoganalytics, "feature_enabled", return_value=True))

            # Stale workflows from a prior run make the worker provision sandboxes for
            # runs that no longer exist, delaying the real eval workflows by 30-60s.
            await terminate_stale_workflows()

            worker = TemporalWorkerThread()
            worker.start()
            stack.callback(worker.stop)

            ctx = self._build_context(len(suites))

            logger.info(
                "Running %d suite(s) on provider=%s with %d sandbox slot(s)",
                len(suites),
                self.options.provider,
                self.options.max_sandboxes,
            )
            results = await asyncio.gather(*(self._run_suite(suite, ctx) for suite in suites))

            ctx.reporter.print_final_summary(results, ctx.log_dirs)
            exit_code = 0 if all(result.status == "passed" for result in results) else 1

            if self.options.fail_under is not None:
                mean = ctx.reporter.mean_score()
                if mean is None:
                    ctx.reporter.print_line(
                        f"\nFAIL   no scores to check against --fail-under {self.options.fail_under:.2f}"
                    )
                    exit_code = 1
                elif mean < self.options.fail_under:
                    ctx.reporter.print_line(
                        f"\nFAIL   mean score {mean * 100:.1f}% is below --fail-under {self.options.fail_under * 100:.1f}%"
                    )
                    exit_code = 1

        return exit_code

    def _build_context(self, suite_count: int) -> EvalContext:
        if self._demo_data is None:
            raise RuntimeError("_bootstrap() must run before the eval context is built")
        return EvalContext(
            provider=self.options.provider,
            provider_strategy=self.provider,
            agent_model=self.options.agent_model,
            case_filter=self.options.case_filter,
            demo_data=self._demo_data,
            posthog_client=self._posthog_client,
            sandbox_slots=asyncio.Semaphore(self.options.max_sandboxes),
            demo_slots=asyncio.Semaphore(DEFAULT_DEMO_COPY_CONCURRENCY),
            reporter=ProgressReporter(total_suites=suite_count),
            per_case_timeout_seconds=self.options.per_case_timeout_seconds,
            trials=self.options.trials,
        )

    async def _run_suite(self, suite: EvalSuite, ctx: EvalContext) -> SuiteRunResult:
        """Run one suite, absorbing its failures so a crash never takes the others down."""
        await ctx.reporter.suite_started(suite.id)
        started = time.monotonic()
        try:
            await suite.fn(ctx)
        except Exception as e:
            logger.exception("Eval suite %s crashed", suite.id)
            result = SuiteRunResult(
                suite_id=suite.id,
                status="crashed",
                error=e,
                duration_seconds=time.monotonic() - started,
            )
        else:
            result = SuiteRunResult(
                suite_id=suite.id,
                status="passed",
                duration_seconds=time.monotonic() - started,
            )
        await ctx.reporter.suite_finished(result)
        return result
