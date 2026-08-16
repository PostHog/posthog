import dataclasses
from functools import cached_property

import pytest

from posthog.dataclasses import REDACTED, asdict_redacted, frozen, sensitive


@frozen
class Point:
    x: int
    y: int


@frozen(slots=False)
class WithCache:
    value: int

    @cached_property
    def doubled(self) -> int:
        return self.value * 2


class TestFrozenDefaults:
    def test_construction_is_keyword_only(self):
        point = Point(x=1, y=2)
        assert (point.x, point.y) == (1, 2)
        with pytest.raises(TypeError):
            Point(1, 2)  # type: ignore[misc]

    def test_instances_are_immutable_and_hashable(self):
        point = Point(x=1, y=2)
        with pytest.raises(dataclasses.FrozenInstanceError):
            point.x = 3  # type: ignore[misc]  # ty: ignore[invalid-assignment]
        assert point == Point(x=1, y=2)
        assert hash(point) == hash(Point(x=1, y=2))
        assert dataclasses.replace(point, x=3) == Point(x=3, y=2)

    def test_slots_by_default(self):
        assert not hasattr(Point(x=1, y=2), "__dict__")

    def test_flags_can_be_overridden(self):
        instance = WithCache(value=21)
        assert instance.doubled == 42


@frozen
class Credentials:
    username: str
    password: str | None = sensitive(default=None)


@frozen
class Connection:
    host: str
    credentials: Credentials | None = None
    fallbacks: list[Credentials] = dataclasses.field(default_factory=list)


class TestSensitiveFields:
    def test_hidden_from_repr(self):
        creds = Credentials(username="svc", password="hunter2")
        assert "hunter2" not in repr(creds)
        assert "svc" in repr(creds)

    def test_asdict_redacted_masks_secrets_recursively(self):
        conn = Connection(
            host="db.example.com",
            credentials=Credentials(username="svc", password="hunter2"),
            fallbacks=[Credentials(username="backup", password="hunter3")],
        )
        redacted = asdict_redacted(conn)
        assert redacted == {
            "host": "db.example.com",
            "credentials": {"username": "svc", "password": REDACTED},
            "fallbacks": [{"username": "backup", "password": REDACTED}],
        }

    def test_asdict_redacted_keeps_none_and_attribute_access(self):
        creds = Credentials(username="svc")
        assert asdict_redacted(creds) == {"username": "svc", "password": None}
        creds = Credentials(username="svc", password="hunter2")
        assert creds.password == "hunter2"

    def test_asdict_redacted_rejects_non_dataclass(self):
        with pytest.raises(TypeError):
            asdict_redacted({"password": "hunter2"})
