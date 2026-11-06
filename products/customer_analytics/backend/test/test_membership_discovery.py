import json
from datetime import timedelta

import pytest
from time_machine import travel
from unittest.mock import patch

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute
from posthog.models.person_group_membership.sql import GROUP_KEY_EXPR
from posthog.personhog_client.proto import (
    CONSISTENCY_LEVEL_STRONG,
    DistinctIdRow,
    GetDistinctIdRowsResponse,
    Group,
    GroupsResponse,
)

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
        self.create_membership()
        if missing_side == "person":
            self.create_group()
            if reassigned_mapping:
                self.create_mapping(self.create_person(deleted=True))
        else:
            self.create_mapping(self.create_person())
        with travel(self.now, tick=False):
            self.run_discovery()
        if missing_side == "person":
            self.create_mapping(self.create_person(), version=2)
        else:
            self.create_group()
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
        assert list(MembershipCleanupCandidate.objects.for_team(self.team.pk).values()) == before
        assert self.get_rows() == [(self.key.distinct_id,)]
        assert MembershipCleanupScan.objects.for_team(self.team.pk).get().cursor == []

    @parameterized.expand([("live",), ("deleted_mapping",), ("deleted_person",), ("orphan",), ("unavailable",)])
    def test_primary_identity_check_protects_membership(self, identity_state: str) -> None:
        self.create_membership()
        self.create_group()
        with travel(self.now, tick=False):
            self.run_discovery()
        row = DistinctIdRow(
            distinct_id=self.key.distinct_id,
            person_id=1,
            is_deleted=identity_state == "deleted_mapping",
        )
        if identity_state != "orphan":
            row.person_is_deleted = identity_state == "deleted_person"
        with (
            travel(self.now + timedelta(days=2), tick=False),
            patch("posthog.models.person.util._get_client") as get_client,
        ):
            lookup = get_client.return_value.get_distinct_id_rows
            lookup.return_value = GetDistinctIdRowsResponse(rows=[row])
            if identity_state == "unavailable":
                lookup.side_effect = RuntimeError("identity unavailable")
                with self.assertRaisesRegex(RuntimeError, "identity unavailable"):
                    self.run_discovery()
            else:
                result = self.run_discovery()
                assert MembershipCleanupCandidate.objects.for_team(self.team.pk).exists() == (identity_state != "live")
                assert result.recovered == (1 if identity_state == "live" else 0)
            assert lookup.call_args.args[0].read_options.consistency == CONSISTENCY_LEVEL_STRONG
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
        ]
    )
    def test_escaped_group_keys_preserve_membership(self, _name: str, group_key: str) -> None:
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
        self.create_group(group_key.replace("\x00", "\ufffd"))
        self.run_discovery()
        with travel(self.now + timedelta(days=2), tick=False):
            assert self.run_discovery().discovered == 0
        assert self.get_rows() == [(self.key.distinct_id,)]
        assert not MembershipCleanupCandidate.objects.for_team(self.team.pk).exists()

    @parameterized.expand([("live",), ("missing",), ("unavailable",)])
    def test_primary_group_check_protects_membership(self, group_state: str) -> None:
        self.key = MembershipKey(group_type_index=0, group_key=r"account \"north\"", distinct_id=self.key.distinct_id)
        self.create_membership()
        self.create_mapping(self.create_person())
        self.run_discovery()
        candidates = MembershipCleanupCandidate.objects.for_team(self.team.pk)
        before = list(candidates.values())
        with (
            travel(self.now + timedelta(days=2), tick=False),
            patch("products.customer_analytics.backend.logic.membership.require_personhog_client") as get_client,
        ):
            lookup = get_client.return_value.get_groups
            lookup.return_value = GroupsResponse(
                groups=[
                    Group(
                        id=1,
                        team_id=self.team.pk,
                        group_type_index=self.key.group_type_index,
                        group_key='account "north"',
                    )
                ]
                if group_state == "live"
                else []
            )
            if group_state == "unavailable":
                lookup.side_effect = RuntimeError("group lookup unavailable")
                with self.assertRaisesRegex(RuntimeError, "group lookup unavailable"):
                    self.run_discovery()
                assert list(candidates.values()) == before
            else:
                result = self.run_discovery()
                assert candidates.exists() == (group_state == "missing")
                assert result.recovered == (1 if group_state == "live" else 0)
                assert candidates.exists() == (group_state == "missing")
            request = lookup.call_args.args[0]
            assert request.team_id == self.team.pk
            assert request.group_identifiers[0].group_key == 'account "north"'
            assert request.read_options.consistency == CONSISTENCY_LEVEL_STRONG
            assert "group_properties" not in request.read_options.field_mask
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

    def test_lost_lease_preserves_candidates_and_scan_position(self) -> None:
        self.create_membership()
        with travel(self.now, tick=False):
            self.run_discovery()
        candidates = list(MembershipCleanupCandidate.objects.for_team(self.team.pk).values())
        with patch("products.customer_analytics.backend.logic.membership.get_redis_client") as redis:
            lease = redis.return_value.lock.return_value
            lease.extend.side_effect = RuntimeError("lease lost")
            with self.assertRaisesRegex(RuntimeError, "lease lost"):
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
