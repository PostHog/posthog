from parameterized import parameterized
from redis.exceptions import NoPermissionError

from posthog.redbeat_preflight import Denial, find_denials, report

KEY_PREFIX = "redbeat:"
STATICS_KEY = "redbeat::statics"
LOCK_KEY = "redbeat::lock"


class FakePipeline:
    def __init__(self, client: "FakeRedis") -> None:
        self.client = client
        self.queued: list[str] = []

    def __enter__(self) -> "FakePipeline":
        return self

    def __exit__(self, *args: object) -> None:
        pass

    def hset(self, *args: object) -> None:
        self.queued.append("hset")

    def hsetnx(self, *args: object) -> None:
        self.queued.append("hsetnx")

    def zadd(self, *args: object) -> None:
        self.queued.append("zadd")

    def execute(self) -> None:
        for command in self.queued:
            self.client.run(command)


class FakeRedis:
    def __init__(self, denied: set[str] | None = None) -> None:
        self.denied = denied or set()
        self.attempted: list[str] = []
        self.deleted: list[str] = []

    def run(self, command: str) -> None:
        self.attempted.append(command)
        if command in self.denied:
            raise NoPermissionError(f"User posthog has no permissions to run the '{command}' command")

    def pipeline(self) -> FakePipeline:
        return FakePipeline(self)

    def smembers(self, key: str) -> None:
        self.run("smembers")

    def sadd(self, *args: object) -> None:
        self.run("sadd")

    def srem(self, *args: object) -> None:
        self.run("srem")

    def hget(self, *args: object) -> None:
        self.run("hget")

    def zrangebyscore(self, *args: object, **kwargs: object) -> None:
        self.run("zrangebyscore")

    def zrem(self, *args: object) -> None:
        self.run("zrem")

    def set(self, *args: object, **kwargs: object) -> None:
        self.run("set")

    def eval(self, *args: object) -> None:
        self.run("eval")

    def delete(self, *keys: str) -> None:
        self.run("del")
        self.deleted.extend(keys)


class TestRedbeatPreflight:
    def test_a_permissive_redis_produces_no_denials(self):
        client = FakeRedis()

        assert find_denials(client, STATICS_KEY, KEY_PREFIX, LOCK_KEY) == []

    def test_scratch_keys_are_deleted(self):
        client = FakeRedis()

        find_denials(client, STATICS_KEY, KEY_PREFIX, LOCK_KEY)

        assert all(key.startswith(f"{KEY_PREFIX}preflight:") for key in client.deleted)
        assert STATICS_KEY not in client.deleted

    def test_a_refused_command_is_named_with_the_grant_to_add(self):
        client = FakeRedis(denied={"smembers"})

        denials = find_denials(client, STATICS_KEY, KEY_PREFIX, LOCK_KEY)
        message = report("redis://posthog:pw@redis:6379/", KEY_PREFIX, denials)

        assert [denial.commands for denial in denials] == [("smembers",)]
        assert "no permissions to run the 'smembers' command" in message
        assert "ACL SETUSER posthog +smembers ~redbeat:*" in message

    @parameterized.expand(
        [
            ("redis://:pw@redis:6379/", "default"),
            ("redis://redis:6379/", "default"),
            ("redis://us%40er:pw@redis:6379/", "us@er"),
        ]
    )
    def test_the_hint_names_the_user_the_connection_authenticates_as(self, url: str, expected_user: str):
        message = report(url, KEY_PREFIX, [Denial(commands=("smembers",), reason="denied")])

        assert f"ACL SETUSER {expected_user} +smembers ~redbeat:*" in message

    def test_a_refused_command_does_not_stop_the_remaining_probes(self):
        client = FakeRedis(denied={"smembers", "eval"})

        denials = find_denials(client, STATICS_KEY, KEY_PREFIX, LOCK_KEY)

        assert [denial.commands for denial in denials] == [("smembers",), ("eval", "get", "pttl", "pexpire")]

    def test_the_lock_commands_are_not_required_when_the_lock_is_disabled(self):
        client = FakeRedis(denied={"set", "eval"})

        assert find_denials(client, STATICS_KEY, KEY_PREFIX, None) == []
        assert "eval" not in client.attempted
