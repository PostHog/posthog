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

import re
from collections.abc import Callable
from typing import Any
from urllib.parse import unquote, urlsplit
from uuid import uuid4

from redis.exceptions import ExecAbortError, NoPermissionError, RedisError

from posthog.dataclasses import frozen

# RedBeat holds its lock with SET NX PX and refreshes it through a Lua script. Redis checks
# the commands inside a script against the calling user too, so one run of this script covers
# the whole refresh path that runs on every tick.
LOCK_REFRESH_PROBE_SCRIPT = """
    redis.call('get', KEYS[1])
    redis.call('pttl', KEYS[1])
    redis.call('pexpire', KEYS[1], ARGV[1])
    return 1
"""

_SCRATCH_LOCK_TTL_MS = 10_000

_REFUSED_COMMAND = re.compile(r"no permissions to run the '([^']+)' command")


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
    def empty_transaction() -> None:
        # RedBeat saves an entry inside MULTI/EXEC. The pair is probed with nothing queued so that
        # each refusal stays separate and keeps its own reason: Redis answers a denied MULTI with
        # NOPERM, and a denied EXEC with EXECABORT that quotes the NOPERM. A pipeline of the real
        # writes reports neither, because redis-py drops the MULTI reason when it reads the EXEC
        # reply, and one refused write would name every command in the pipeline.
        client.execute_command("MULTI")
        client.execute_command("EXEC")

    def refresh_lock() -> None:
        # RedBeat and redis-py both run the lock scripts through register_script, which sends
        # EVALSHA and falls back to SCRIPT LOAD when the server's script cache misses. Those are
        # the commands to probe: an ACL can allow EVAL and refuse either of them, and beat then
        # dies on its first lock refresh.
        sha = client.script_load(LOCK_REFRESH_PROBE_SCRIPT)
        client.evalsha(sha, 1, scratch.lock, _SCRATCH_LOCK_TTL_MS)

    probes = [
        Probe(commands=("smembers",), run=lambda: client.smembers(statics_key)),
        Probe(commands=("sadd",), run=lambda: client.sadd(scratch.statics, "preflight")),
        Probe(commands=("srem",), run=lambda: client.srem(scratch.statics, "preflight")),
        Probe(commands=("hset",), run=lambda: client.hset(scratch.entry, "definition", "preflight")),
        Probe(commands=("hsetnx",), run=lambda: client.hsetnx(scratch.entry, "meta", "preflight")),
        Probe(commands=("zadd",), run=lambda: client.zadd(scratch.schedule, {scratch.entry: 0})),
        Probe(commands=("multi", "exec"), run=empty_transaction),
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
            Probe(commands=("script|load", "evalsha", "get", "pttl", "pexpire"), run=refresh_lock),
        ]

    return probes


def _refused_command(reason: str) -> str | None:
    """The command Redis named in a refusal, when it named one."""
    match = _REFUSED_COMMAND.search(reason)
    return match.group(1) if match else None


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
            except (NoPermissionError, ExecAbortError) as exc:
                # A refused EXEC aborts the transaction instead of answering NOPERM, so its
                # refusal arrives as EXECABORT. Nothing else in these probes opens a transaction.
                reason = str(exc)
                refused = _refused_command(reason)
                if refused is not None and refused not in probe.commands:
                    # The refusal names a command no probe sends, so it comes from the connection
                    # setup that runs first. redis-py sends SELECT there when the URL names a
                    # database other than 0. Every probe fails the same way until that command is
                    # granted, so it is the one grant worth reporting.
                    return [Denial(commands=(refused,), reason=reason)]
                denials.append(Denial(commands=probe.commands, reason=reason))
        return denials
    finally:
        try:
            client.delete(*scratch.all)
        except RedisError:
            pass


def _acl_hint(url: str, key_prefix: str, denials: list[Denial]) -> str:
    # A URL with no username authenticates as Redis's default ACL user, and redis-py decodes a
    # percent-encoded username before it authenticates. ACL SETUSER on any other name creates a
    # new user instead of granting the command, so the hint must name the user beat connects as.
    username = urlsplit(url).username
    user = unquote(username) if username else "default"
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
