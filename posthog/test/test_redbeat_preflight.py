from parameterized import parameterized
from redis.exceptions import ExecAbortError, NoPermissionError

from posthog.redbeat_preflight import Denial, find_denials, report

KEY_PREFIX = "redbeat:"
STATICS_KEY = "redbeat::statics"
LOCK_KEY = "redbeat::lock"
LOCK_SCRIPT_COMMANDS = ("script|load", "evalsha", "get", "pttl", "pexpire")


class FakeRedis:
    def __init__(self, denied: set[str] | None = None, refused_on_connect: str | None = None) -> None:
        self.denied = denied or set()
        self.refused_on_connect = refused_on_connect
        self.attempted: list[str] = []
        self.deleted: list[str] = []

    def run(self, command: str) -> None:
        self.attempted.append(command)
        if self.refused_on_connect:
            raise NoPermissionError(f"User posthog has no permissions to run the '{self.refused_on_connect}' command")
        if command in self.denied:
            raise NoPermissionError(f"User posthog has no permissions to run the '{command}' command")

    def execute_command(self, command: str) -> None:
        # Redis refuses EXEC by aborting the transaction, and quotes the refusal in that reply.
        if command == "EXEC" and "exec" in self.denied:
            self.attempted.append("exec")
            raise ExecAbortError(
                "Transaction discarded because of: NOPERM User posthog has no permissions to run the 'exec' command"
            )
        self.run(command.lower())

    def hset(self, *args: object) -> None:
        self.run("hset")

    def hsetnx(self, *args: object) -> None:
        self.run("hsetnx")

    def zadd(self, *args: object) -> None:
        self.run("zadd")

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

    def script_load(self, *args: object) -> str:
        self.run("script|load")
        return "sha"

    def evalsha(self, *args: object) -> None:
        self.run("evalsha")

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
        client = FakeRedis(denied={"smembers", "evalsha"})

        denials = find_denials(client, STATICS_KEY, KEY_PREFIX, LOCK_KEY)

        assert [denial.commands for denial in denials] == [("smembers",), LOCK_SCRIPT_COMMANDS]

    @parameterized.expand(
        [
            ({"hset"}, [("hset",)]),
            ({"multi"}, [("multi", "exec")]),
            ({"exec"}, [("multi", "exec")]),
            ({"smembers", "multi"}, [("smembers",), ("multi", "exec")]),
            ({"evalsha"}, [LOCK_SCRIPT_COMMANDS]),
            ({"script|load"}, [LOCK_SCRIPT_COMMANDS]),
        ]
    )
    def test_a_refusal_names_only_the_commands_its_own_probe_needs(
        self, denied: set[str], expected: list[tuple[str, ...]]
    ):
        client = FakeRedis(denied=denied)

        denials = find_denials(client, STATICS_KEY, KEY_PREFIX, LOCK_KEY)

        assert [denial.commands for denial in denials] == expected

    def test_a_refusal_from_the_connection_setup_names_that_command_alone(self):
        client = FakeRedis(refused_on_connect="select")

        denials = find_denials(client, STATICS_KEY, KEY_PREFIX, LOCK_KEY)
        message = report("redis://posthog:pw@redis:6379/1", KEY_PREFIX, denials)

        assert [denial.commands for denial in denials] == [("select",)]
        assert "ACL SETUSER posthog +select ~redbeat:*" in message

    def test_the_lock_commands_are_not_required_when_the_lock_is_disabled(self):
        client = FakeRedis(denied={"set", "evalsha"})

        assert find_denials(client, STATICS_KEY, KEY_PREFIX, None) == []
        assert "evalsha" not in client.attempted
