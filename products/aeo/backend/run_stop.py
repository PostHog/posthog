import threading

from posthog.redis import get_client

# Long enough for a setup job to reach the step that queues the run, short enough that a stop nobody
# consumed doesn't skip a later scheduled run.
STOP_REQUEST_TTL_SECONDS = 5 * 60
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
    get_client().set(_key(team_id), "1", ex=STOP_REQUEST_TTL_SECONDS)


def clear_stop(team_id: int) -> None:
    get_client().delete(_key(team_id))


def stop_requested(team_id: int) -> bool:
    return bool(get_client().exists(_key(team_id)))


def watch_for_stop(team_id: int, done: threading.Event, stop: threading.Event) -> None:
    while not done.wait(STOP_POLL_SECONDS):
        try:
            if stop_requested(team_id):
                stop.set()
                return
        except Exception:
            # A Redis blip must not end the watch; the next tick asks again.
            continue
