import datetime as dt
import dataclasses

from posthog.dataclasses import frozen


@frozen
class ConnectionOptions:
    host: str
    port: int
    namespace: str = "default"


@frozen
class MTLSOptions:
    client_cert: str | None = None
    client_private_key: str | None = dataclasses.field(default=None, repr=False)
    domain: str | None = None
    server_root_ca_cert: str | None = None


@frozen
class ConcurrencyOptions:
    max_concurrent_activities: int | None = None
    max_concurrent_activity_task_polls: int | None = None
    max_concurrent_workflow_tasks: int | None = None
    max_concurrent_workflow_task_polls: int | None = None


@frozen
class TunerOptions:
    target_memory_usage: float
    target_cpu_usage: float = 1.0


@frozen
class SlotOptions:
    maximum_slots: int | None = None
    minimum_slots: int | None = None
    ramp_throttle: dt.timedelta | None = None


@frozen
class WorkerOptions:
    task_queue: str
    graceful_shutdown_timeout: dt.timedelta = dt.timedelta(minutes=5)
