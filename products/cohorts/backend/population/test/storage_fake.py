"""In-memory stand-in for the object storage the input store writes to.

A fake with real semantics rather than a mock: chunks come back exactly as they went in, a deleted
chunk really is gone, and a missing key is missing. That is what lets a test assert resume behavior
instead of asserting which calls were made.
"""

from contextlib import contextmanager

from unittest.mock import patch

from products.cohorts.backend.population import input_store


class FakeObjectStorage:
    def __init__(self) -> None:
        self.objects: dict[str, str] = {}

    def write(self, key: str, content: str) -> None:
        self.objects[key] = content

    def read(self, key: str, *, missing_ok: bool = False):
        if key not in self.objects and not missing_ok:
            raise KeyError(key)
        return self.objects.get(key)

    def delete_objects(self, keys: list[str]) -> list[str]:
        for key in keys:
            self.objects.pop(key, None)
        return []


@contextmanager
def fake_population_storage():
    storage = FakeObjectStorage()
    with (
        patch.object(input_store, "object_storage", storage),
        patch.object(input_store, "_require_storage", return_value=storage),
        patch.object(
            input_store,
            "_input_keys",
            side_effect=lambda prefix: [key for key in storage.objects if key.startswith(f"{prefix}/")],
        ),
    ):
        yield storage
