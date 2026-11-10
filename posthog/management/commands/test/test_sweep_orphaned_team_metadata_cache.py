import re
import dataclasses
from io import StringIO
from uuid import uuid4

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import OperationalError
from django.test import override_settings

from parameterized import parameterized

from posthog.caching.flags_redis_cache import FLAGS_DEDICATED_CACHE_ALIAS
from posthog.models.utils import mask_key_value
from posthog.storage import object_storage
from posthog.storage.hypercache import HyperCache, HyperCacheStoreMissing
from posthog.storage.team_metadata_cache import TEAM_HYPERCACHE_MANAGEMENT_CONFIG

COMMAND_MODULE = "posthog.management.commands.sweep_orphaned_team_metadata_cache"


@override_settings(
    OBJECT_STORAGE_ENABLED=True,
    CACHES={
        "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
        FLAGS_DEDICATED_CACHE_ALIAS: {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "redis://stub:6379/",
        },
    },
)
class TestSweepOrphanedTeamMetadataCache(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        # A namespace of its own keeps the sweep away from entries other tests write to the shared bucket.
        self.hypercache = HyperCache(
            namespace=f"sweep_test_{uuid4().hex}",
            value="full_metadata.json",
            token_based=True,
            load_fn=lambda key: HyperCacheStoreMissing(),
        )
        config_patch = patch(
            f"{COMMAND_MODULE}.TEAM_HYPERCACHE_MANAGEMENT_CONFIG",
            dataclasses.replace(TEAM_HYPERCACHE_MANAGEMENT_CONFIG, hypercache=self.hypercache),
        )
        config_patch.start()
        self.addCleanup(config_patch.stop)

        self.hypercache.set_cache_value(self.team, {"id": self.team.id})
        self.addCleanup(self.hypercache.delete_cache_entry, self.team.api_token)

    def _write_orphan(self, prefix: str = "phc_orphan_") -> str:
        token = f"{prefix}{uuid4().hex}"
        self.hypercache.set_cache_value(token, {"id": 999999})
        self.addCleanup(self.hypercache.delete_cache_entry, token)
        return token

    def _entry_exists(self, token: str) -> bool:
        key = self.hypercache.get_cache_key(token)
        in_s3 = object_storage.read(key, missing_ok=True) is not None
        in_redis = self.hypercache.cache_client.get(key) is not None
        assert in_s3 == in_redis
        return in_s3

    def _run(self, *args: str) -> str:
        out = StringIO()
        call_command("sweep_orphaned_team_metadata_cache", *args, stdout=out)
        return out.getvalue()

    @parameterized.expand([("dry_run", [], True), ("delete", ["--delete"], False)])
    def test_sweep_reports_orphans_and_deletes_only_with_flag(
        self, _name: str, args: list[str], orphan_survives: bool
    ) -> None:
        orphans = [self._write_orphan(), self._write_orphan(prefix="phc_custom/")]
        sibling_cache = HyperCache(
            namespace=self.hypercache.namespace,
            value="other.json",
            token_based=True,
            load_fn=lambda key: HyperCacheStoreMissing(),
        )
        sibling_only_token = f"phc_sibling_{uuid4().hex}"
        sibling_cache.set_cache_value(sibling_only_token, {"id": 999999})
        self.addCleanup(sibling_cache.delete_cache_entry, sibling_only_token)

        output = self._run(*args)

        for orphan in orphans:
            assert mask_key_value(orphan) in output
            assert orphan not in output
            assert self._entry_exists(orphan) is orphan_survives
        assert self.team.api_token not in output
        assert mask_key_value(sibling_only_token) not in output
        assert self._entry_exists(self.team.api_token)
        assert object_storage.read(sibling_cache.get_cache_key(sibling_only_token), missing_ok=True) is not None

    def test_limit_stops_after_n_orphans_across_batches(self) -> None:
        orphans = [self._write_orphan() for _ in range(3)]

        self._run("--delete", "--limit", "2", "--batch-size", "2")

        assert [self._entry_exists(token) for token in orphans].count(False) == 2
        assert self._entry_exists(self.team.api_token)

    def test_team_lookup_error_in_a_later_batch_deletes_nothing(self) -> None:
        orphans = [self._write_orphan(), self._write_orphan()]

        with (
            patch(
                "posthog.storage.hypercache_manager.existing_team_identifiers",
                side_effect=[set(), OperationalError("down")],
            ),
            pytest.raises(OperationalError),
        ):
            self._run("--delete", "--batch-size", "1")

        assert all(self._entry_exists(token) for token in orphans)

    def test_redis_delete_failure_keeps_the_object_for_the_next_sweep(self) -> None:
        orphan = self._write_orphan()

        with (
            patch.object(self.hypercache.cache_client, "delete", side_effect=ConnectionError("down")),
            pytest.raises(CommandError, match=re.escape(mask_key_value(orphan))),
        ):
            self._run("--delete")

        assert self._entry_exists(orphan)

        self._run("--delete")

        assert not self._entry_exists(orphan)
