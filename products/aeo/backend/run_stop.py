import time
import threading

from posthog.redis import get_client

# A stop records when it was asked for, and a run stops only for a stop asked after the run was queued, so a stop
# never needs clearing and a run queued later is never skipped by it. It outlives setup's model calls (two 5-minute
# deadlines) plus a first run's wait for the lease (40 tries 15 seconds apart).
STOP_REQUEST_TTL_SECONDS = 30 * 60
STOP_POLL_SECONDS = 2


# A run queued by setup waits at most this long for a run still finishing, so a lost task can't look queued forever.
RUN_QUEUED_TTL_SECONDS = 15 * 60


def lease_key(team_id: int) -> str:
    return f"aeo_citation_run:{team_id}"


def _queued_key(team_id: int) -> str:
    return f"aeo_citation_run_queued:{team_id}"


def mark_run_queued(team_id: int) -> None:
    get_client().set(_queued_key(team_id), "1", ex=RUN_QUEUED_TTL_SECONDS)


def clear_run_queued(team_id: int) -> None:
    get_client().delete(_queued_key(team_id))


def checks_running(team_id: int) -> bool:
    client = get_client()
    return bool(client.exists(_queued_key(team_id)) or client.exists(lease_key(team_id)))


def _key(team_id: int) -> str:
    return f"aeo_citation_run_stop:{team_id}"


def request_stop(team_id: int) -> None:
    get_client().set(_key(team_id), repr(time.time()), ex=STOP_REQUEST_TTL_SECONDS)


def stop_requested(team_id: int, *, since: float = 0.0) -> bool:
    """Whether a stop was asked for at or after `since`, the time the run was queued."""
    value = get_client().get(_key(team_id))
    if value is None:
        return False
    try:
        requested_at = float(value)
    except ValueError:
        # A stop stored before stops carried a time applies to every run.
        return True
    return requested_at >= since


def watch_for_stop(team_id: int, done: threading.Event, stop: threading.Event, *, since: float) -> None:
    while not done.wait(STOP_POLL_SECONDS):
        try:
            if stop_requested(team_id, since=since):
                stop.set()
                return
        except Exception:
            # A Redis blip must not end the watch; the next tick asks again.
            continue
