import asyncio
import signal
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import threading
import time
import objgraph
import tracemalloc
import gc
import collections

from temporalio.runtime import PrometheusConfig, Runtime, TelemetryConfig
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.temporal.common.client import connect
from posthog.temporal.common.sentry import SentryInterceptor


def monitor_memory(interval=30):
    while True:
        print("\n=== Most Common Object Types in Memory ===")  # noqa: T201
        objgraph.show_most_common_types(limit=20)
        time.sleep(interval)


def monitor_memory_2(interval=30, limit=20):
    """Thread function to monitor and print memory usage by type."""
    tracemalloc.start()

    while True:
        # Collect garbage to get an accurate snapshot
        gc.collect()

        # Take a memory snapshot
        snapshot = tracemalloc.take_snapshot()

        # Group memory usage by object type
        stats = collections.defaultdict(int)

        for stat in snapshot.statistics("traceback"):
            # Get the object type from the traceback
            for frame in stat.traceback:
                obj_type = frame.filename
                stats[obj_type] += stat.size

        # Sort by memory size
        sorted_stats = sorted(stats.items(), key=lambda x: x[1], reverse=True)

        print("\n=== Top Memory Allocations by Type ===")  # noqa: T201
        for obj_type, size in sorted_stats[:limit]:
            print(f"{obj_type}: {size / 1024 / 1024:.2f} MB")  # noqa: T201

        time.sleep(interval)


async def start_worker(
    host,
    port,
    metrics_port,
    namespace,
    task_queue,
    workflows,
    activities,
    server_root_ca_cert=None,
    client_cert=None,
    client_key=None,
    max_concurrent_workflow_tasks=None,
    max_concurrent_activities=None,
):
    runtime = Runtime(telemetry=TelemetryConfig(metrics=PrometheusConfig(bind_address=f"0.0.0.0:{metrics_port:d}")))
    client = await connect(
        host,
        port,
        namespace,
        server_root_ca_cert,
        client_cert,
        client_key,
        runtime=runtime,
    )

    worker = Worker(
        client,
        task_queue=task_queue,
        workflows=workflows,
        activities=activities,
        workflow_runner=UnsandboxedWorkflowRunner(),
        graceful_shutdown_timeout=timedelta(minutes=5),
        interceptors=[SentryInterceptor()],
        activity_executor=ThreadPoolExecutor(max_workers=max_concurrent_activities or 50),
        max_concurrent_activities=max_concurrent_activities or 50,
        max_concurrent_workflow_tasks=max_concurrent_workflow_tasks,
    )

    monitor_thread = threading.Thread(target=monitor_memory_2, args=(30, 20), daemon=True)
    monitor_thread.start()

    # catch the TERM signal, and stop the worker gracefully
    # https://github.com/temporalio/sdk-python#worker-shutdown
    async def shutdown_worker():
        await worker.shutdown()

    loop = asyncio.get_event_loop()
    loop.add_signal_handler(signal.SIGTERM, lambda: asyncio.create_task(shutdown_worker()))

    await worker.run()
