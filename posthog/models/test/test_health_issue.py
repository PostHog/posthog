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
