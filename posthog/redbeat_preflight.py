"""Check that Redis lets RedBeat run the commands it needs, before beat starts.

RedBeat reads the static schedule set with SMEMBERS in its ``setup_schedule``, before it
installs a single entry. A Redis ACL that does not grant that command makes the command
fail, and ``celery beat`` exits with the raw exception. Beat is a background job of
``bin/docker-worker-celery``, so its exit takes the whole worker container down and the
operator sees a restart loop instead of a configuration error.

This module probes the commands RedBeat uses against throwaway keys under the same key
prefix, and reports every command the ACL refuses.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from redis.exceptions import NoPermissionError, RedisError

from posthog.dataclasses import frozen

# RedBeat holds its lock with SET NX PX and refreshes it through a Lua script. Redis checks
# the commands inside a script against the calling user too, so one EVAL probe covers the
# whole refresh path that runs on every tick.
LOCK_REFRESH_PROBE_SCRIPT = """
    redis.call('get', KEYS[1])
    redis.call('pttl', KEYS[1])
    redis.call('pexpire', KEYS[1], ARGV[1])
    return 1
"""

_SCRATCH_LOCK_TTL_MS = 10_000


@frozen
class Denial:
    """The commands one probe needs, and the reason Redis gave for refusing it."""

    commands: tuple[str, ...]
    reason: str


@frozen
class ScratchKeys:
    """Throwaway keys the probes write to, under RedBeat's own key prefix."""

    statics: str
    entry: str
    schedule: str
    lock: str

    @classmethod
    def under(cls, key_prefix: str) -> ScratchKeys:
        base = f"{key_prefix}preflight:{uuid4().hex}"
        return cls(statics=f"{base}:statics", entry=f"{base}:entry", schedule=f"{base}:schedule", lock=f"{base}:lock")

    @property
    def all(self) -> tuple[str, ...]:
        return (self.statics, self.entry, self.schedule, self.lock)


@frozen
class Probe:
    commands: tuple[str, ...]
    run: Callable[[], Any]


def _probes(client: Any, statics_key: str, scratch: ScratchKeys, lock_key: str | None) -> list[Probe]:
    def save_entry() -> None:
        # RedBeat saves an entry in a MULTI/EXEC pipeline, so this probe covers those too.
        with client.pipeline() as pipe:
            pipe.hset(scratch.entry, "definition", "preflight")
            pipe.hsetnx(scratch.entry, "meta", "preflight")
            pipe.zadd(scratch.schedule, {scratch.entry: 0})
            pipe.execute()

    probes = [
        Probe(commands=("smembers",), run=lambda: client.smembers(statics_key)),
        Probe(commands=("sadd",), run=lambda: client.sadd(scratch.statics, "preflight")),
        Probe(commands=("srem",), run=lambda: client.srem(scratch.statics, "preflight")),
        Probe(commands=("hset", "hsetnx", "zadd", "multi", "exec"), run=save_entry),
        Probe(commands=("hget",), run=lambda: client.hget(scratch.entry, "definition")),
        Probe(commands=("zrangebyscore",), run=lambda: client.zrangebyscore(scratch.schedule, 0, 0)),
        Probe(commands=("zrem",), run=lambda: client.zrem(scratch.schedule, scratch.entry)),
        Probe(commands=("del",), run=lambda: client.delete(scratch.entry)),
    ]

    if lock_key:
        probes += [
            Probe(
                commands=("set",),
                run=lambda: client.set(scratch.lock, "preflight", nx=True, px=_SCRATCH_LOCK_TTL_MS),
            ),
            Probe(
                commands=("eval", "get", "pttl", "pexpire"),
                run=lambda: client.eval(LOCK_REFRESH_PROBE_SCRIPT, 1, scratch.lock, _SCRATCH_LOCK_TTL_MS),
            ),
        ]

    return probes


def find_denials(client: Any, statics_key: str, key_prefix: str, lock_key: str | None) -> list[Denial]:
    """Run every command RedBeat needs and return the ones the ACL refused.

    Writes go to throwaway keys under ``key_prefix``, so the probe matches the same key
    patterns an ACL would without touching the live schedule.
    """
    scratch = ScratchKeys.under(key_prefix)
    try:
        denials = []
        for probe in _probes(client, statics_key, scratch, lock_key):
            try:
                probe.run()
            except NoPermissionError as exc:
                denials.append(Denial(commands=probe.commands, reason=str(exc)))
        return denials
    finally:
        try:
            client.delete(*scratch.all)
        except RedisError:
            pass


def _acl_hint(url: str, key_prefix: str, denials: list[Denial]) -> str:
    user = urlsplit(url).username or "<user>"
    grants = " ".join(f"+{command}" for denial in denials for command in denial.commands)
    return f"ACL SETUSER {user} {grants} ~{key_prefix}*"


def report(url: str, key_prefix: str, denials: list[Denial]) -> str:
    lines = ["Redis refused commands the beat scheduler needs:"]
    lines += [f"  {' '.join(denial.commands)}: {denial.reason}" for denial in denials]
    lines += [
        "Beat cannot install its schedule without these, so no periodic task can run.",
        f"Grant them on the scheduler's keys, for example: {_acl_hint(url, key_prefix, denials)}",
        "Or set REDBEAT_REDIS_URL to a Redis that allows them.",
    ]
    return "\n".join(lines)
