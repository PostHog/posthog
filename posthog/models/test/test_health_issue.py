from posthog.test.base import BaseTest

from django.db import IntegrityError

from parameterized import parameterized

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
        self.assertIsNotNone(issue.id)
        self.assertEqual(issue.status, HealthIssue.Status.ACTIVE)
        self.assertIsNotNone(issue.created_at)

    def test_compute_unique_hash_deterministic(self):
        payload = {"key": "value", "number": 42}
        hash1 = HealthIssue.compute_unique_hash("test_kind", payload)
        hash2 = HealthIssue.compute_unique_hash("test_kind", payload)
        self.assertEqual(hash1, hash2)
        self.assertEqual(len(hash1), 64)

    def test_compute_unique_hash_with_hash_keys(self):
        payload = {"important": "value", "transient": "ignored"}
        hash1 = HealthIssue.compute_unique_hash("test", payload, hash_keys=["important"])
        hash2 = HealthIssue.compute_unique_hash(
            "test", {"important": "value", "transient": "different"}, hash_keys=["important"]
        )
        self.assertEqual(hash1, hash2)

    def test_compute_unique_hash_with_hash_keys_order_independent(self):
        payload = {"a": "1", "b": "2", "c": "3"}
        hash1 = HealthIssue.compute_unique_hash("test", payload, hash_keys=["b", "a"])
        hash2 = HealthIssue.compute_unique_hash("test", payload, hash_keys=["a", "b"])
        self.assertEqual(hash1, hash2)

    def test_upsert_creates_new_issue(self):
        issue, created = HealthIssue.upsert_issue(
            team_id=self.team.id,
            kind="test_issue",
            severity="warning",
            payload={"detail": "test"},
        )
        self.assertTrue(created)
        self.assertEqual(issue.kind, "test_issue")
        self.assertEqual(issue.status, HealthIssue.Status.ACTIVE)

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
        self.assertTrue(created1)
        self.assertFalse(created2)
        self.assertEqual(issue1.id, issue2.id)
        issue2.refresh_from_db()
        self.assertEqual(issue2.severity, "critical")

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
        self.assertNotEqual(issue1.id, issue2.id)

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

    @parameterized.expand(
        [
            ("resolve", HealthIssue.Status.RESOLVED),
            ("dismiss", HealthIssue.Status.DISMISSED),
        ]
    )
    def test_status_transitions(self, method_name, expected_status):
        issue = HealthIssue.objects.create(
            team=self.team,
            kind="test_kind",
            severity="warning",
            payload={},
            unique_hash="test_hash",
        )
        getattr(issue, method_name)()
        issue.refresh_from_db()
        self.assertEqual(issue.status, expected_status)

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
        self.assertIsNotNone(issue.resolved_at)

    def test_reactivate_clears_resolved_at(self):
        issue = HealthIssue.objects.create(
            team=self.team,
            kind="test_kind",
            severity="warning",
            payload={},
            unique_hash="test_hash",
        )
        issue.resolve()
        issue.reactivate()
        issue.refresh_from_db()
        self.assertEqual(issue.status, HealthIssue.Status.ACTIVE)
        self.assertIsNone(issue.resolved_at)
