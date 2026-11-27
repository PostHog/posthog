import json
import tempfile
from pathlib import Path
from typing import Any

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.integrations.backend.fake_backend import FakeBackend
from posthog.integrations.backend.service_transport import IntegrationServiceError, ServiceTransport
from posthog.integrations.mirror.client import MAX_BODY_BYTES, MirrorClient, MirrorOrigin, MirrorOutcome, MirrorResult
from posthog.integrations.mirror.snapshot import MirrorDelete, MirrorRow, MirrorUpsert
from posthog.integrations.test.credentials_service_stub import CredentialsServiceStub, write_signing_key

URL = "http://credentials-service.test"
TEAM = 7
SHARED_FIXTURE = Path(__file__).resolve().parents[4] / "services/credentials-service/tests/fixtures/mirror-request.json"


def _upsert(legacy_id: int, *, config: dict[str, Any] | None = None, **overrides: Any) -> MirrorUpsert:
    fields: dict[str, Any] = {
        "legacy_id": legacy_id,
        "kind": "slack",
        "source_version": 1,
        "integration_id": None,
        "auth_type": "oauth",
        "is_source_row": False,
        "config": config or {},
        "sensitive_config": {"access_token": "fake-token"},
        "legacy_unreadable_keys": (),
        "errors": "",
        "created_by_id": None,
        "created_at": "2024-01-01T00:00:00.000000+00:00",
    }
    return MirrorUpsert(**{**fields, **overrides})


def _row_from_fixture(body: dict[str, Any]) -> MirrorRow:
    if body["deleted"]:
        return MirrorDelete(
            legacy_id=body["legacy_id"],
            kind=body["kind"],
            tombstone=body["tombstone"],
            source_version=body.get("source_version"),
        )
    fields = {key: value for key, value in body.items() if key != "deleted"}
    fields["legacy_unreadable_keys"] = tuple(fields["legacy_unreadable_keys"])
    return MirrorUpsert(**fields)


class TestMirrorClient(SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        key_path, public_key = write_signing_key(directory.name)
        settings_override = override_settings(
            CREDENTIALS_SERVICE_URL=URL, CREDENTIALS_SERVICE_INTEGRATIONS_SIGNING_KEY_PATH=key_path
        )
        settings_override.enable()
        self.addCleanup(settings_override.disable)
        self.stub = CredentialsServiceStub(FakeBackend(), public_key)
        self.client = MirrorClient(ServiceTransport(session=self.stub))  # type: ignore[arg-type]

    def test_body_matches_the_shared_service_fixture(self) -> None:
        fixture = json.loads(SHARED_FIXTURE.read_text())
        rows = [_row_from_fixture(body) for body in fixture["rows"]]

        self.client.mirror(TEAM, rows, origin=MirrorOrigin(fixture["origin"]), force=fixture["force"])

        assert self.stub.mirror_bodies == [fixture]

    def test_token_is_owned_by_the_team_and_holds_only_mirror(self) -> None:
        self.client.mirror(TEAM, [_upsert(1), _upsert(2, kind="hubspot")], origin=MirrorOrigin.WRITE)

        [(method, path, claims, _headers)] = self.stub.calls
        assert (method, path) == ("PUT", "/mirror")
        assert claims["owner"] == {"type": "team", "id": TEAM}
        assert claims["ops"] == ["mirror"]
        assert claims["kinds"] == ["hubspot", "slack"]

    @parameterized.expand(
        [
            ("one_row", 1, 0, [1]),
            ("exactly_one_full_request", 100, 0, [100]),
            ("one_over_the_row_cap", 101, 0, [100, 1]),
            ("many_small_rows", 250, 0, [100, 100, 50]),
            ("two_rows_per_byte_budget", 5, 200 * 1024, [2, 2, 1]),
            ("a_row_over_the_byte_budget_goes_alone", 3, MAX_BODY_BYTES, [1, 1, 1]),
        ]
    )
    def test_splits_requests_by_row_count_and_body_size(
        self, _name: str, row_count: int, padding: int, expected_sizes: list[int]
    ) -> None:
        rows = [_upsert(legacy_id, config={"padding": "x" * padding}) for legacy_id in range(1, row_count + 1)]

        results = self.client.mirror(TEAM, rows, origin=MirrorOrigin.BACKFILL)

        assert [len(body["rows"]) for body in self.stub.mirror_bodies] == expected_sizes
        assert all(len(json.dumps(body)) <= MAX_BODY_BYTES * 1.1 for body in self.stub.mirror_bodies)
        assert [result.legacy_id for result in results] == list(range(1, row_count + 1))
        assert {result.outcome for result in results} == {MirrorOutcome.CREATED}

    @parameterized.expand(
        [
            ("created", {"outcome": "created", "id": "a"}, MirrorOutcome.CREATED, False),
            ("updated", {"outcome": "updated", "id": "a"}, MirrorOutcome.UPDATED, False),
            ("deleted", {"outcome": "deleted", "id": "a"}, MirrorOutcome.DELETED, False),
            ("unchanged", {"outcome": "unchanged", "id": "a"}, MirrorOutcome.UNCHANGED, False),
            ("stale", {"outcome": "stale", "id": "a"}, MirrorOutcome.STALE, False),
            ("absent", {"outcome": "absent"}, MirrorOutcome.ABSENT, False),
            ("owner_mismatch", {"outcome": "owner_mismatch"}, MirrorOutcome.OWNER_MISMATCH, False),
            ("rejected", {"outcome": "rejected", "code": "forbidden_kind"}, MirrorOutcome.REJECTED, False),
            ("key_conflict", {"outcome": "conflict", "conflicting_legacy_id": 9}, MirrorOutcome.CONFLICT, False),
            (
                "foreign_key_conflict",
                {"outcome": "conflict", "conflicting_legacy_id": None},
                MirrorOutcome.CONFLICT,
                False,
            ),
            ("lost_race", {"outcome": "conflict", "code": "concurrent_write"}, MirrorOutcome.CONFLICT, True),
        ]
    )
    def test_parses_each_outcome(
        self, _name: str, answer: dict[str, Any], outcome: MirrorOutcome, retryable: bool
    ) -> None:
        self.stub.mirror_answers[1] = [answer]

        [result] = self.client.mirror(TEAM, [_upsert(1)], origin=MirrorOrigin.WRITE)

        assert result == MirrorResult(
            legacy_id=1,
            outcome=outcome,
            id=answer.get("id"),
            conflicting_legacy_id=answer.get("conflicting_legacy_id"),
            code=answer.get("code"),
        )
        assert result.retryable is retryable

    @parameterized.expand(
        [
            ("unknown_outcome", {"outcome": "merged"}),
            ("no_outcome", {}),
        ]
    )
    def test_refuses_an_undocumented_result(self, _name: str, answer: dict[str, Any]) -> None:
        self.stub.mirror_answers[1] = [answer]

        with self.assertRaises(IntegrationServiceError) as caught:
            self.client.mirror(TEAM, [_upsert(1)], origin=MirrorOrigin.WRITE)

        assert caught.exception.code == "bad_response"
