from posthog.test.base import BaseTest

from django.db import IntegrityError

from posthog.models.health_issue import HealthIssue


class TestHealthIssue(BaseTest):
    def test_create_health_issue(self):
        issue = HealthIssue.objects.create(
            team=self.team,
            kind="sdk_outdated",
            severity=HealthIssue.Severity.WARNING,
            payload={"sdk_version": "1.0.0", "latest_version": "2.0.0"},
            unique_hash="test_hash",
        )
        assert issue.id is not None
        assert issue.status == HealthIssue.Status.ACTIVE
        assert issue.created_at is not None

    def test_compute_unique_hash_deterministic(self):
        payload = {"key": "value", "number": 42}
        hash1 = HealthIssue.compute_unique_hash("test_kind", payload)
        hash2 = HealthIssue.compute_unique_hash("test_kind", payload)
        assert hash1 == hash2
        assert len(hash1) == 64

    def test_compute_unique_hash_with_hash_keys(self):
        payload = {"important": "value", "transient": "ignored"}
        hash1 = HealthIssue.compute_unique_hash("test", payload, hash_keys=["important"])
        hash2 = HealthIssue.compute_unique_hash(
            "test", {"important": "value", "transient": "different"}, hash_keys=["important"]
        )
        assert hash1 == hash2

    def test_compute_unique_hash_with_hash_keys_order_independent(self):
        payload = {"a": "1", "b": "2", "c": "3"}
        hash1 = HealthIssue.compute_unique_hash("test", payload, hash_keys=["b", "a"])
        hash2 = HealthIssue.compute_unique_hash("test", payload, hash_keys=["a", "b"])
        assert hash1 == hash2

    def test_upsert_creates_new_issue(self):
        issue, created = HealthIssue.upsert_issue(
            team_id=self.team.id,
            kind="test_issue",
            severity="warning",
            payload={"detail": "test"},
        )
        assert created
        assert issue.kind == "test_issue"
        assert issue.status == HealthIssue.Status.ACTIVE

    def test_upsert_updates_existing_active_issue(self):
        issue1, created1 = HealthIssue.upsert_issue(
            team_id=self.team.id,
            kind="test_issue",
            severity="warning",
            payload={"detail": "test"},
        )
        issue2, created2 = HealthIssue.upsert_issue(
            team_id=self.team.id,
            kind="test_issue",
            severity="critical",
            payload={"detail": "test"},
        )
        assert created1
        assert not created2
        assert issue1.id == issue2.id
        issue2.refresh_from_db()
        assert issue2.severity == "critical"

    def test_partial_unique_constraint_allows_resolved_duplicates(self):
        issue1 = HealthIssue.objects.create(
            team=self.team,
            kind="test_kind",
            severity="warning",
            payload={},
            unique_hash="same_hash",
            status=HealthIssue.Status.RESOLVED,
        )
        issue2 = HealthIssue.objects.create(
            team=self.team,
            kind="test_kind",
            severity="warning",
            payload={},
            unique_hash="same_hash",
            status=HealthIssue.Status.ACTIVE,
        )
        assert issue1.id != issue2.id

    def test_partial_unique_constraint_blocks_active_duplicates(self):
        HealthIssue.objects.create(
            team=self.team,
            kind="test_kind",
            severity="warning",
            payload={},
            unique_hash="same_hash",
            status=HealthIssue.Status.ACTIVE,
        )
        with self.assertRaises(IntegrityError):
            HealthIssue.objects.create(
                team=self.team,
                kind="test_kind",
                severity="warning",
                payload={},
                unique_hash="same_hash",
                status=HealthIssue.Status.ACTIVE,
            )

    def test_resolve_transitions_status(self):
        issue = HealthIssue.objects.create(
            team=self.team,
            kind="test_kind",
            severity="warning",
            payload={},
            unique_hash="test_hash",
        )
        issue.resolve()
        issue.refresh_from_db()
        assert issue.status == HealthIssue.Status.RESOLVED

    def test_resolve_already_resolved_raises(self):
        issue = HealthIssue.objects.create(
            team=self.team,
            kind="test_kind",
            severity="warning",
            payload={},
            unique_hash="test_hash",
            status=HealthIssue.Status.RESOLVED,
        )
        with self.assertRaises(ValueError):
            issue.resolve()

    def test_resolve_sets_resolved_at(self):
        issue = HealthIssue.objects.create(
            team=self.team,
            kind="test_kind",
            severity="warning",
            payload={},
            unique_hash="test_hash",
        )
        issue.resolve()
        issue.refresh_from_db()
        assert issue.resolved_at is not None

    def _bulk_payload(self, unique_hash: str, severity: str = "warning") -> dict:
        return {
            "team_id": self.team.id,
            "severity": severity,
            "payload": {"detail": unique_hash},
            "unique_hash": unique_hash,
        }

    def test_bulk_upsert_returns_newly_created_issues(self):
        created = HealthIssue.bulk_upsert("test_kind", [self._bulk_payload("a"), self._bulk_payload("b")])
        assert {i.unique_hash for i in created} == {"a", "b"}
        assert all(i.status == HealthIssue.Status.ACTIVE for i in created)

    def test_bulk_upsert_does_not_return_already_active_issues(self):
        HealthIssue.bulk_upsert("test_kind", [self._bulk_payload("a", severity="warning")])
        second_pass = HealthIssue.bulk_upsert("test_kind", [self._bulk_payload("a", severity="critical")])
        assert second_pass == []

        existing = HealthIssue.objects.get(team=self.team, kind="test_kind", unique_hash="a")
        assert existing.severity == "critical"

    def test_bulk_upsert_returns_reactivated_issue(self):
        first = HealthIssue.bulk_upsert("test_kind", [self._bulk_payload("a")])
        assert len(first) == 1
        first[0].resolve()

        reactivated = HealthIssue.bulk_upsert("test_kind", [self._bulk_payload("a")])
        assert len(reactivated) == 1
        assert reactivated[0].unique_hash == "a"
        assert reactivated[0].status == HealthIssue.Status.ACTIVE
        assert reactivated[0].id != first[0].id

    def test_bulk_upsert_empty_input_returns_empty_list(self):
        assert HealthIssue.bulk_upsert("test_kind", []) == []

    def test_bulk_resolve_returns_transitioned_rows(self):
        created = HealthIssue.bulk_upsert("test_kind", [self._bulk_payload("a"), self._bulk_payload("b")])
        assert len(created) == 2

        resolved = HealthIssue.bulk_resolve("test_kind", {self.team.id})
        assert {i.unique_hash for i in resolved} == {"a", "b"}
        assert all(i.status == HealthIssue.Status.RESOLVED for i in resolved)
        assert all(i.resolved_at is not None for i in resolved)

    def test_bulk_resolve_with_keep_hashes_skips_active(self):
        HealthIssue.bulk_upsert("test_kind", [self._bulk_payload("a"), self._bulk_payload("b")])
        resolved = HealthIssue.bulk_resolve("test_kind", {self.team.id}, keep_hashes={self.team.id: {"a"}})
        assert {i.unique_hash for i in resolved} == {"b"}
        assert HealthIssue.objects.filter(unique_hash="a", status=HealthIssue.Status.ACTIVE).exists()

    def test_bulk_resolve_empty_team_ids_returns_empty_list(self):
        assert HealthIssue.bulk_resolve("test_kind", set()) == []

    def test_bulk_resolve_no_active_issues_returns_empty_list(self):
        resolved = HealthIssue.bulk_resolve("test_kind", {self.team.id})
        assert resolved == []

    def test_bulk_upsert_skips_deleted_team_and_persists_remaining(self):
        # Reproduces the FK violation that previously rolled back the entire
        # batch when a team_id snapshotted at workflow start was deleted before
        # bulk_upsert ran.
        missing_team_id = self.team.id + 999_999
        result = HealthIssue.bulk_upsert(
            "test_kind",
            [
                self._bulk_payload("good"),
                {
                    "team_id": missing_team_id,
                    "severity": "warning",
                    "payload": {"detail": "orphan"},
                    "unique_hash": "orphan",
                },
            ],
        )
        assert {i.unique_hash for i in result} == {"good"}
        assert HealthIssue.objects.filter(team=self.team, kind="test_kind", unique_hash="good").exists()
        assert not HealthIssue.objects.filter(unique_hash="orphan").exists()

    def test_bulk_upsert_all_teams_missing_returns_empty(self):
        missing_team_id = self.team.id + 999_999
        result = HealthIssue.bulk_upsert(
            "test_kind",
            [
                {
                    "team_id": missing_team_id,
                    "severity": "warning",
                    "payload": {"detail": "orphan"},
                    "unique_hash": "orphan",
                }
            ],
        )
        assert result == []
        assert not HealthIssue.objects.filter(unique_hash="orphan").exists()
