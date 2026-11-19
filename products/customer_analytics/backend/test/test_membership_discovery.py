import re
import json
from datetime import timedelta
from time import monotonic

import pytest
from time_machine import travel
from unittest.mock import patch

from clickhouse_driver import Client
from parameterized import parameterized

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.execute import _get_kill_switch_level, _get_kill_switch_team_sets
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models.instance_setting import override_instance_config
from posthog.models.person_group_membership.sql import GROUP_KEY_EXPR

from products.customer_analytics.backend.logic.membership import MembershipKey
from products.customer_analytics.backend.logic.membership_discovery import (
    MembershipDiscoveryCounts,
    MembershipDiscoveryInput,
    MembershipDiscoveryStore,
    list_membership_discovery_teams,
    record_membership_discovery_team,
    run_membership_discovery,
)
from products.customer_analytics.backend.models.membership_cleanup import (
    MembershipCleanupCandidate,
    MembershipCleanupScan,
)
from products.customer_analytics.backend.test.membership_test_utils import MembershipTestCase


@pytest.mark.usefixtures("membership_cleanup_tables")
class TestMembershipDiscovery(MembershipTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.store = MembershipDiscoveryStore()

    def run_discovery(self) -> MembershipDiscoveryCounts:
        return run_membership_discovery(MembershipDiscoveryInput(team_id=self.team.pk), self.store)

    @parameterized.expand([(None,), (100,)])
    def test_discovery_queries_work_with_development_tag_guard(self, remaining: int | None) -> None:
        self.create_membership()
        self.create_mapping(self.create_person())
        self.create_group()
        self.store.deadline = monotonic() + remaining if remaining is not None else None
        execute = Client.execute
        observed_settings: list[dict[str, object]] = []

        def execute_with_limits(client: Client, query: str, *args: object, **kwargs: object) -> object:
            if "WHERE team_id = " in query:
                settings = kwargs["settings"]
                assert isinstance(settings, dict)
                assert settings["max_execution_time"] == 15
                assert settings["max_threads"] == 30
                assert settings["max_bytes_to_read"] == 1000000000000
                assert settings["max_block_size"] == 321
                observed_settings.append(settings)
            return execute(client, query, *args, **kwargs)

        _get_kill_switch_level.cache_clear()
        _get_kill_switch_team_sets.cache_clear()
        try:
            with (
                patch("posthog.clickhouse.client.execute.DEBUG", True),
                patch("posthog.clickhouse.client.execute.TEST", False),
                patch.dict(
                    "products.customer_analytics.backend.logic.membership.QUERY_SETTINGS", {"max_execution_time": 100}
                ),
                override_instance_config("CLICKHOUSE_KILL_SWITCH", "off"),
                override_instance_config("CLICKHOUSE_KILL_SWITCH_FULL_TEAMS", [self.team.pk]),
                override_instance_config("CLICKHOUSE_KILL_SWITCH_LIGHT_TEAMS", []),
                patch.dict(
                    "posthog.clickhouse.client.execute.CLICKHOUSE_PER_TEAM_QUERY_SETTINGS",
                    {str(self.team.pk): {"max_block_size": 321}},
                    clear=True,
                ),
                patch.object(Client, "execute", execute_with_limits),
                tags_context(product=None, feature=None),
            ):
                assert list_membership_discovery_teams(self.store) == [self.team.pk]
                assert self.run_discovery().scanned == 1
                assert self.run_discovery().discovered == 0
                with tags_context(product=Product.CUSTOMER_ANALYTICS, feature=Feature.DATA_DELETION):
                    assert self.store.get_existing_keys(self.team.pk, {self.key}) == {self.key}
        finally:
            _get_kill_switch_level.cache_clear()
            _get_kill_switch_team_sets.cache_clear()
        assert observed_settings
        assert not MembershipCleanupCandidate.objects.for_team(self.team.pk).exists()

    @parameterized.expand([("live_team", False), ("deleted_team", True)])
    def test_erased_membership_clears_candidates(self, _name: str, deleted_team: bool) -> None:
        team_id = self.team.pk + 1000000 if deleted_team else self.team.pk
        self.create_membership(team_id=team_id)
        input = MembershipDiscoveryInput(team_id=team_id)
        assert run_membership_discovery(input, self.store).discovered == 2
        sync_execute(
            "ALTER TABLE sharded_person_group_membership DELETE WHERE team_id = %(team_id)s",
            {"team_id": team_id},
            settings={"mutations_sync": 2},
        )
        for _ in range(2):
            assert run_membership_discovery(input, self.store).discovered == 0
            assert not MembershipCleanupCandidate.objects.for_team(team_id).exists()

    @parameterized.expand([("person",), ("group",)])
    def test_discovery_preserves_membership_and_first_missing_time(self, missing_side: str) -> None:
        self.create_membership()
        if missing_side == "person":
            self.create_group()
        else:
            self.create_mapping(self.create_person())
        with travel(self.now, tick=False):
            assert self.run_discovery().discovered == 1
        with travel(self.now + timedelta(days=2), tick=False):
            assert self.run_discovery().discovered == 0
        candidate = MembershipCleanupCandidate.objects.for_team(self.team.pk).get()
        assert candidate.missing_side == missing_side
        assert candidate.first_missing_at == self.now
        assert self.get_rows() == [(self.key.distinct_id,)]

    @parameterized.expand([("person", False), ("person", True), ("group", False)])
    def test_recovered_match_clears_candidate(self, missing_side: str, reassigned_mapping: bool) -> None:
        self.restore_missing_membership(missing_side, reassigned_mapping)
        with travel(self.now + timedelta(hours=25), tick=False):
            assert self.run_discovery().recovered == 1
        assert self.get_rows() == [(self.key.distinct_id,)]
        assert not MembershipCleanupCandidate.objects.for_team(self.team.pk).exists()

    def test_lookup_failure_preserves_candidates_and_cursor(self) -> None:
        self.create_membership()
        with travel(self.now, tick=False):
            self.run_discovery()
        before = list(MembershipCleanupCandidate.objects.for_team(self.team.pk).values())
        with patch(
            "products.customer_analytics.backend.logic.membership_discovery.get_membership_existence",
            side_effect=RuntimeError("lookup unavailable"),
        ):
            with self.assertRaisesRegex(RuntimeError, "lookup unavailable"):
                self.run_discovery()
        self.assert_membership_state(before, [])

    @parameterized.expand([("live",), ("deleted_mapping",), ("deleted_person",), ("orphan",), ("unavailable",)])
    def test_primary_identity_check_protects_membership(self, identity_state: str) -> None:
        self.create_membership()
        self.create_group()
        with travel(self.now, tick=False):
            self.run_discovery()
        with self.primary_person_lookup(identity_state):
            if identity_state == "unavailable":
                with self.assertRaisesRegex(RuntimeError, "identity unavailable"):
                    self.run_discovery()
            else:
                result = self.run_discovery()
                assert MembershipCleanupCandidate.objects.for_team(self.team.pk).exists() == (identity_state != "live")
                assert result.recovered == (1 if identity_state == "live" else 0)
        if identity_state in ("live", "unavailable"):
            assert self.get_rows() == [(self.key.distinct_id,)]
            assert MembershipCleanupCandidate.objects.for_team(self.team.pk).exists() == (
                identity_state == "unavailable"
            )
        else:
            assert self.get_rows() == [(self.key.distinct_id,)]

    @parameterized.expand(
        [
            ("quotes", 'account "north"'),
            ("backslash", r"account\north"),
            ("newline", "account\nnorth"),
            ("object", '{"id":"account"}'),
            ("array", '["account"]'),
            ("nul", "account\x00north"),
            ("high_surrogate", "account\ud800north"),
            ("low_surrogate", "account\udcffnorth"),
            ("surrogate_pair", "account\U0001f600north"),
            ("max_length", "\U0001f600" * 400),
        ]
    )
    def test_escaped_group_keys_preserve_membership(self, _name: str, group_key: str) -> None:
        if _name in ("high_surrogate", "low_surrogate"):
            stored_key = json.dumps(group_key)[1:-1]
        else:
            # nosemgrep: clickhouse-fstring-param-audit -- GROUP_KEY_EXPR is a fixed ingestion expression.
            stored_key = sync_execute(
                f"SELECT {GROUP_KEY_EXPR} FROM (SELECT %(properties)s AS properties, 0 AS group_type_index)",
                {
                    "properties": json.dumps(
                        {"$group_0": json.loads(group_key) if _name in ("object", "array") else group_key}
                    )
                },
            )[0][0]
        self.key = MembershipKey(group_type_index=0, group_key=stored_key, distinct_id=self.key.distinct_id)
        self.create_membership()
        self.create_mapping(self.create_person())
        self.create_group(re.sub(r"[\ud800-\udfff\x00]", "\ufffd", group_key))
        self.run_discovery()
        with travel(self.now + timedelta(days=2), tick=False):
            assert self.run_discovery().discovered == 0
        assert self.get_rows() == [(self.key.distinct_id,)]
        assert not MembershipCleanupCandidate.objects.for_team(self.team.pk).exists()

    def test_large_group_keys_do_not_block_discovery_or_candidate_rechecks(self) -> None:
        self.create_mapping(self.create_person())
        for index in range(25):
            self.create_membership(
                MembershipKey(
                    group_type_index=0, group_key=f"large-{index}-" + "a" * 400000, distinct_id=self.key.distinct_id
                )
            )
        assert self.run_discovery().discovered == 25
        MembershipCleanupScan.objects.for_team(self.team.pk).update(cursor=[1, "", ""])
        assert self.run_discovery().discovered == 0
        candidates = MembershipCleanupCandidate.objects.for_team(self.team.pk)
        assert candidates.count() == 25
        assert set(candidates.values_list("missing_side", flat=True)) == {"group"}
        assert len(self.get_rows()) == 25

    @parameterized.expand([("live",), ("missing",), ("unavailable",)])
    def test_primary_group_check_protects_membership(self, group_state: str) -> None:
        self.key = MembershipKey(group_type_index=0, group_key=r"account \"north\"", distinct_id=self.key.distinct_id)
        self.create_membership()
        self.create_mapping(self.create_person())
        self.run_discovery()
        candidates = MembershipCleanupCandidate.objects.for_team(self.team.pk)
        before = list(candidates.values())
        with self.primary_group_lookup(group_state):
            if group_state == "unavailable":
                with self.assertRaisesRegex(RuntimeError, "group lookup unavailable"):
                    self.run_discovery()
                assert list(candidates.values()) == before
            else:
                result = self.run_discovery()
                assert candidates.exists() == (group_state == "missing")
                assert result.recovered == (1 if group_state == "live" else 0)
                assert candidates.exists() == (group_state == "missing")
        assert self.get_rows() == [(self.key.distinct_id,)]

    def test_team_discovery_resumes_after_last_processed_team(self) -> None:
        self.create_membership()
        later_team_id = self.team.pk + 1000000
        self.create_membership(team_id=later_team_id)
        assert list_membership_discovery_teams(self.store) == [self.team.pk, later_team_id]
        assert list_membership_discovery_teams(self.store) == [self.team.pk, later_team_id]
        record_membership_discovery_team(self.team.pk)
        assert list_membership_discovery_teams(self.store) == [later_team_id]
        record_membership_discovery_team(later_team_id)
        assert list_membership_discovery_teams(self.store) == []
        assert list_membership_discovery_teams(self.store) == [self.team.pk, later_team_id]

    @parameterized.expand([("lease",), ("deadline",)])
    def test_lost_lease_preserves_candidates_and_scan_position(self, failure: str) -> None:
        self.create_membership()
        self.run_discovery()
        candidates = list(MembershipCleanupCandidate.objects.for_team(self.team.pk).values())
        with patch("products.customer_analytics.backend.logic.membership.get_redis_client") as redis:
            lease = redis.return_value.lock.return_value
            if failure == "deadline":
                self.store.deadline = monotonic() - 1
                error_type: type[Exception] = TimeoutError
            else:
                lease.extend.side_effect = RuntimeError("lease lost")
                error_type = RuntimeError
            with self.assertRaises(error_type):
                self.run_discovery()
        assert list(MembershipCleanupCandidate.objects.for_team(self.team.pk).values()) == candidates
        assert MembershipCleanupScan.objects.for_team(self.team.pk).get().cursor == []
        assert self.get_rows() == [(self.key.distinct_id,)]

    def test_scan_clears_recovery_outside_pending_page(self) -> None:
        self.create_membership()
        self.create_group()
        self.run_discovery()
        other = MembershipKey(group_type_index=0, group_key="later-account", distinct_id="later-person")
        self.create_membership(other)
        self.run_discovery()
        MembershipCleanupCandidate.objects.for_team(self.team.pk).filter(distinct_id=other.distinct_id).update(
            last_checked_at=self.now - timedelta(days=1)
        )
        self.create_mapping(self.create_person())
        with patch("products.customer_analytics.backend.logic.membership_discovery.BATCH_SIZE", 1):
            self.run_discovery()
        assert (
            not MembershipCleanupCandidate.objects.for_team(self.team.pk)
            .filter(distinct_id=self.key.distinct_id)
            .exists()
        )
        assert MembershipCleanupCandidate.objects.for_team(self.team.pk).filter(distinct_id=other.distinct_id).exists()

    def test_scan_resumes_after_page_boundary(self) -> None:
        self.create_membership()
        other = MembershipKey(group_type_index=0, group_key="later-account", distinct_id="later-person")
        self.create_membership(other)
        with patch("products.customer_analytics.backend.logic.membership_discovery.BATCH_SIZE", 1):
            assert self.run_discovery().has_more
            scan = MembershipCleanupScan.objects.for_team(self.team.pk).get()
            assert scan.cursor == [other.group_type_index, other.group_key, other.distinct_id]
            assert not self.run_discovery().has_more
            scan.refresh_from_db()
            assert scan.cursor == []
        assert MembershipCleanupCandidate.objects.for_team(self.team.pk).count() == 4

    def test_deleted_team_discovery_keeps_config_and_avoids_identity_reads(self) -> None:
        team_id = self.team.pk + 1000000
        self.create_membership(team_id=team_id)
        sync_execute(
            "INSERT INTO person_group_membership_config (team_id, group_type_index, enabled, version) VALUES",
            [(team_id, 0, 1, 1)],
        )
        with patch(
            "products.customer_analytics.backend.logic.membership_discovery.get_membership_existence",
            side_effect=RuntimeError("identity unavailable"),
        ):
            assert run_membership_discovery(MembershipDiscoveryInput(team_id=team_id), self.store).discovered == 2
        assert self.get_rows(team_id) == [(self.key.distinct_id,)]
        assert sync_execute(
            "SELECT count() FROM distributed_person_group_membership_config WHERE team_id = %(team_id)s",
            {"team_id": team_id},
        ) == [(1,)]
