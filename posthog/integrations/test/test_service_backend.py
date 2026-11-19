import time
import tempfile
from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta
from typing import Any

from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, TestCase, override_settings

import jwt
import requests
from parameterized import parameterized

from posthog.integrations import IntegrationManager, IntegrationPatch
from posthog.integrations.backend import DjangoBackend, configured_backend, service_backend, use_backend
from posthog.integrations.backend.fake_backend import FakeBackend
from posthog.integrations.backend.protocol import KindScope, RowFilter, RowScope, SourceRows
from posthog.integrations.backend.service_backend import (
    IntegrationServiceError,
    IntegrationServiceUnavailable,
    ServiceBackend,
)
from posthog.integrations.contracts import (
    CrossTeamFilter,
    IntegrationConflict,
    IntegrationNotFound,
    UnsupportedAuthType,
)
from posthog.integrations.test.credentials_service_stub import CredentialsServiceStub, response, write_signing_key
from posthog.models import Organization, Project, Team
from posthog.models.integration import UndecryptedIntegrationSecretError

URL = "http://credentials-service.test"
TEAM = 2
OTHER_TEAM = 3


class _CannedSession:
    """Answers every request with the same response."""

    def __init__(self, answer: requests.Response) -> None:
        self.answer = answer
        self.calls = 0

    def request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        self.calls += 1
        return self.answer


class _DropFirstAnswer:
    """Sends the first request to the stub, then drops the connection before the answer arrives."""

    def __init__(self, stub: CredentialsServiceStub, method: str) -> None:
        self.stub = stub
        self.method = method
        self.dropped = False

    def request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        answer = self.stub.request(method, url, **kwargs)
        if method == self.method and not self.dropped:
            self.dropped = True
            raise requests.ConnectionError("connection reset")
        return answer


class TestServiceBackend(TestCase):
    # Not a SimpleTestCase: an SDK delete runs the delete hooks of the products in a transaction of the
    # Django database, because the rows that refer to an integration stay there. See `lifecycle.py`.
    # The hooks read team-scoped models, so the teams the rows belong to must exist.

    @classmethod
    def setUpTestData(cls) -> None:
        organization = Organization.objects.create(name="Integrations")
        for team_id in (TEAM, OTHER_TEAM):
            project = Project.objects.create(id=team_id, organization=organization)
            Team.objects.create(id=team_id, project=project, organization=organization)

    def setUp(self) -> None:
        super().setUp()
        self.fake = FakeBackend()
        self.key_path, self.public_key = write_signing_key(self.enterContext(tempfile.TemporaryDirectory()))
        self.stub = CredentialsServiceStub(self.fake, self.public_key)
        self.offset = 0.0
        self.enterContext(
            override_settings(
                CREDENTIALS_SERVICE_URL=URL,
                CREDENTIALS_SERVICE_INTEGRATIONS_SIGNING_KEY_PATH=self.key_path,
                CREDENTIALS_SERVICE_JWT_SECRET="",
            )
        )
        self.backend = self._use(self.stub)

    def _use(self, session: Any) -> ServiceBackend:
        backend = ServiceBackend(session=session, clock=lambda: time.time() + self.offset)
        self.enterContext(use_backend(backend))
        return backend

    def _seed(self, external_id: str, *, team_id: int = TEAM, kind: str = "github", **config: Any) -> int:
        return self.fake.seed(
            team_id=team_id,
            kind=kind,
            external_id=external_id,
            config=config,
            sensitive_config={"access_token": f"token-{external_id}", "refresh_token": "never-exposed"},
        ).id

    def _calls(self, path_prefix: str = "") -> list[tuple[str, str]]:
        return [(method, path) for method, path, _claims, _headers in self.stub.calls if path.startswith(path_prefix)]

    @parameterized.expand(
        [
            (
                "get_resolves_one_ref",
                lambda ids: IntegrationManager.github.oauth.get(TEAM, ids["a"]),
                [("POST", "/resolve", {"owner": TEAM, "ops": ["resolve", "read"], "refs": ["{ref}"]})],
            ),
            (
                "list_names_the_kinds_then_resolves",
                lambda ids: IntegrationManager.github.oauth.list(TEAM),
                [
                    ("GET", "", {"owner": TEAM, "ops": ["read"], "kinds": ["github"]}),
                    ("POST", "/resolve", {"owner": TEAM, "ops": ["resolve", "read"], "refs": ["{ref}"]}),
                ],
            ),
            (
                "create_names_the_kind_and_the_user",
                lambda ids: IntegrationManager.slack.oauth.create(TEAM, external_id="new", config={}, created_by_id=7),
                [("POST", "", {"owner": TEAM, "ops": ["write"], "kinds": ["slack"], "user_id": 7})],
            ),
            (
                "update_reads_then_patches_one_ref",
                lambda ids: IntegrationManager.github.oauth.update(TEAM, ids["a"], errors="x"),
                [
                    (
                        "GET",
                        "/{ref}",
                        {"owner": TEAM, "ops": ["read", "write"], "kinds": ["github"], "refs": ["{ref}"]},
                    ),
                    (
                        "PATCH",
                        "/{ref}",
                        {"owner": TEAM, "ops": ["read", "write"], "kinds": ["github"], "refs": ["{ref}"]},
                    ),
                    ("POST", "/resolve", {"owner": TEAM, "ops": ["resolve", "read"], "refs": ["{ref}"]}),
                ],
            ),
            (
                "delete_reads_then_deletes_one_ref",
                lambda ids: IntegrationManager.github.oauth.delete(TEAM, ids["a"], ignore_usages=True),
                [
                    # The accessor reads the row first, to hand it to the delete hooks.
                    ("POST", "/resolve", {"owner": TEAM, "ops": ["resolve", "read"], "refs": ["{ref}"]}),
                    (
                        "GET",
                        "/{ref}",
                        {"owner": TEAM, "ops": ["read", "delete"], "kinds": ["github"], "refs": ["{ref}"]},
                    ),
                    (
                        "DELETE",
                        "/{ref}",
                        {"owner": TEAM, "ops": ["read", "delete"], "kinds": ["github"], "refs": ["{ref}"]},
                    ),
                ],
            ),
            (
                "list_across_teams_has_no_owner",
                lambda ids: IntegrationManager.github.oauth.list_across_teams(CrossTeamFilter()),
                [("POST", "/list-across-teams", {"ops": ["list_across_teams"], "kinds": ["github"]})],
            ),
            (
                "update_by_external_id_has_no_owner",
                lambda ids: IntegrationManager.github.oauth.update_by_external_id("a", IntegrationPatch(errors="x")),
                [
                    ("GET", "/by-external-id/github/a", {"ops": ["read_by_external_id"], "kinds": ["github"]}),
                    ("PATCH", "/by-external-id/github/a", {"ops": ["write_by_external_id"], "kinds": ["github"]}),
                ],
            ),
        ]
    )
    def test_each_request_carries_a_token_for_its_step(
        self, _name: str, action: Callable[[dict[str, int]], Any], expected: list[tuple[str, str, dict[str, Any]]]
    ) -> None:
        ref = str(self._seed("a"))
        expected = [
            (method, path.format(ref=ref), {**claims, "refs": [ref]} if "refs" in claims else claims)
            for method, path, claims in expected
        ]

        action({"a": int(ref)})

        seen = []
        for method, path, claims, _headers in self.stub.calls:
            assert claims["aud"] == "posthog:credentials_service:integrations"
            assert claims["exp"] - claims["iat"] == 60
            assert claims["caller"] == "integrations"
            narrowed: dict[str, Any] = {
                key: claims[key] for key in ("ops", "kinds", "refs", "user_id") if key in claims
            }
            if "owner" in claims:
                assert claims["owner"]["type"] == "team"
                narrowed["owner"] = claims["owner"]["id"]
            seen.append((method, path, narrowed))
        assert seen == expected
        jtis = [claims["jti"] for _method, _path, claims, _headers in self.stub.calls]
        assert len(set(jtis)) == len(jtis)

    @parameterized.expand(
        [
            ("not_found", 404, IntegrationNotFound, None),
            ("forbidden_kind", 403, IntegrationNotFound, None),
            ("conflict", 409, IntegrationConflict, None),
            ("version_mismatch", 412, IntegrationConflict, None),
            ("unsupported_auth_type", 422, UnsupportedAuthType, None),
            ("unreadable_secret", 422, UndecryptedIntegrationSecretError, None),
            ("validation", 400, IntegrationServiceError, "validation"),
            ("forbidden_op", 403, IntegrationServiceError, "forbidden_op"),
            ("forbidden_ref", 403, IntegrationServiceError, "forbidden_ref"),
            ("kms_unavailable", 503, IntegrationServiceUnavailable, "kms_unavailable"),
            ("internal", 500, IntegrationServiceUnavailable, "internal"),
        ]
    )
    def test_error_codes_map_to_sdk_exceptions(
        self, code: str, status: int, expected: type[Exception], service_code: str | None
    ) -> None:
        self._use(_CannedSession(response(status, {"error": {"code": code, "message": "m", "details": {}}})))

        with self.assertRaises(expected) as raised:
            IntegrationManager.github.oauth.update(TEAM, 1, errors="x")

        if service_code is not None:
            assert type(raised.exception) is expected
            assert raised.exception.code == service_code  # type: ignore[attr-defined]

    @parameterized.expand(
        [
            ("bare_401", response(401), IntegrationServiceError, "unauthorized"),
            ("html_502", response(502), IntegrationServiceUnavailable, "unknown"),
        ]
    )
    def test_answers_without_an_error_body(
        self, _name: str, answer: requests.Response, expected: type[Exception], code: str
    ) -> None:
        self._use(_CannedSession(answer))

        with self.assertRaises(expected) as raised:
            IntegrationManager.github.oauth.get(TEAM, 1)

        assert raised.exception.code == code  # type: ignore[attr-defined]

    def test_a_row_without_a_legacy_id_raises(self) -> None:
        record: dict[str, Any] = {
            "id": "00000000-0000-0000-0000-000000000001",
            "legacy_id": None,
            "reference": "00000000-0000-0000-0000-000000000001",
            "team_id": TEAM,
            "kind": "github",
            "integration_id": "a",
            "config": {},
            "errors": "",
            "created_at": "2026-01-01T00:00:00+00:00",
            "created_by_id": None,
            "auth_type": "oauth",
            "is_source_row": False,
            "version": 1,
        }
        self._use(_CannedSession(response(200, {"results": [record], "next": None})))

        with self.assertRaises(IntegrationServiceError) as raised:
            IntegrationManager.github.oauth.list_across_teams(CrossTeamFilter())

        assert raised.exception.code == "no_legacy_id"

    def test_an_unconfigured_backend_sends_nothing(self) -> None:
        session = _CannedSession(response(200, {}))
        self._use(session)

        with override_settings(CREDENTIALS_SERVICE_URL="", CREDENTIALS_SERVICE_INTEGRATIONS_SIGNING_KEY_PATH=""):
            with self.assertRaises(IntegrationServiceError) as raised:
                IntegrationManager.github.oauth.get(TEAM, 1)

        assert (raised.exception.code, session.calls) == ("unconfigured", 0)

    def test_a_missing_key_file_is_a_configuration_error(self) -> None:
        session = _CannedSession(response(200, {}))
        self._use(session)

        with override_settings(CREDENTIALS_SERVICE_INTEGRATIONS_SIGNING_KEY_PATH=f"{self.key_path}.missing"):
            with self.assertRaises(IntegrationServiceError) as raised:
                IntegrationManager.github.oauth.get(TEAM, 1)

        assert (raised.exception.code, session.calls) == ("unconfigured", 0)
        assert "CREDENTIALS_SERVICE_INTEGRATIONS_SIGNING_KEY_PATH" in str(raised.exception)

    def test_a_key_file_that_is_not_ed25519_is_a_configuration_error(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".pem") as bad_key:
            bad_key.write("not a key")
            bad_key.flush()
            with override_settings(CREDENTIALS_SERVICE_INTEGRATIONS_SIGNING_KEY_PATH=bad_key.name):
                with self.assertRaises(IntegrationServiceError) as raised:
                    IntegrationManager.github.oauth.get(TEAM, 1)

        assert raised.exception.code == "unconfigured"

    def test_tokens_use_eddsa_and_never_hs256(self) -> None:
        IntegrationManager.github.oauth.get(TEAM, self._seed("a"))

        assert self.stub.calls
        for _method, _path, _claims, headers in self.stub.calls:
            token = headers["Authorization"].removeprefix("Bearer ")
            assert jwt.get_unverified_header(token)["alg"] == "EdDSA"
            audience = "posthog:credentials_service:integrations"
            jwt.decode(token, self.public_key, audience=audience, algorithms=["EdDSA"])
            # The shared platform secret must not verify a token of this audience.
            with self.assertRaises(jwt.PyJWTError):
                jwt.decode(token, "any-shared-secret", audience=audience, algorithms=["HS256"])

    def test_a_token_signed_with_hs256_is_refused(self) -> None:
        forged = jwt.encode(
            {"aud": "posthog:credentials_service:integrations", "iat": 1, "exp": 2, "jti": "x", "ops": ["read"]},
            "any-shared-secret",
            algorithm="HS256",
        )

        answer = self.stub.request(
            "GET", f"{URL}/v1/integrations", params={}, headers={"Authorization": f"Bearer {forged}"}
        )

        assert answer.status_code == 401

    def test_a_read_across_teams_sends_one_request_for_each_team(self) -> None:
        mine, theirs = self._seed("a"), self._seed("b", team_id=OTHER_TEAM)
        scope = RowScope(kinds=(KindScope(kind="github"),), source_rows=SourceRows.INCLUDE)

        records = self.backend.list(scope, RowFilter(team_ids=(TEAM, OTHER_TEAM)))

        assert {record.id for record in records} == {mine, theirs}
        resolves = [claims for _method, path, claims, _headers in self.stub.calls if path == "/resolve"]
        assert sorted((claims["owner"]["id"], claims["refs"]) for claims in resolves) == [
            (TEAM, [str(mine)]),
            (OTHER_TEAM, [str(theirs)]),
        ]
        assert all(set(claims["ops"]) & {"list_across_teams"} == set() for claims in resolves)

    def test_a_token_has_one_owner_or_none(self) -> None:
        with self.assertRaises(ValueError):
            self.backend._token("get", team_id=None)
        with self.assertRaises(ValueError):
            self.backend._token("list_across_teams", team_id=TEAM)

    @parameterized.expand(
        [
            ("one_connection_error_is_retried", [requests.ConnectionError()], None),
            (
                "two_connection_errors_fail",
                [requests.ConnectionError(), requests.ConnectionError()],
                IntegrationServiceUnavailable,
            ),
            ("a_read_timeout_is_not_retried", [requests.ReadTimeout()], IntegrationServiceUnavailable),
        ]
    )
    def test_transport_failures(self, _name: str, failures: list[Exception], expected: type[Exception] | None) -> None:
        row_id = self._seed("a")
        self.stub.failures = list(failures)

        if expected is None:
            assert IntegrationManager.github.oauth.get(TEAM, row_id).access_token == "token-a"
        else:
            with self.assertRaises(expected):
                IntegrationManager.github.oauth.get(TEAM, row_id)

    def test_a_create_retried_after_a_dropped_answer_creates_one_row(self) -> None:
        self._use(_DropFirstAnswer(self.stub, "POST"))

        row = IntegrationManager.slack.oauth.create(TEAM, external_id="new", config={})

        creates = [headers for method, path, _claims, headers in self.stub.calls if (method, path) == ("POST", "")]
        assert len(creates) == 2
        assert creates[0]["Idempotency-Key"] == creates[1]["Idempotency-Key"]
        assert [r.id for r in self.fake.list(*_every_row(TEAM))] == [row.id]

    def test_a_delete_retried_after_a_dropped_answer_succeeds(self) -> None:
        row_id = self._seed("a")
        self._use(_DropFirstAnswer(self.stub, "DELETE"))

        IntegrationManager.github.oauth.delete(TEAM, row_id, ignore_usages=True)

        assert self.fake.list(*_every_row(TEAM)) == []

    @parameterized.expand([("one_concurrent_write", 1, None), ("every_attempt_conflicts", 3, IntegrationConflict)])
    def test_update_reads_the_row_again_after_a_concurrent_write(
        self, _name: str, concurrent_writes: int, expected: type[Exception] | None
    ) -> None:
        row_id = self._seed("a")
        self.stub.concurrent_writes = concurrent_writes

        if expected is None:
            assert IntegrationManager.github.oauth.update(TEAM, row_id, errors="x").errors == "x"
        else:
            with self.assertRaises(expected):
                IntegrationManager.github.oauth.update(TEAM, row_id, errors="x")

    def test_resolve_cache_serves_reads_until_the_ttl_and_writes_invalidate_it(self) -> None:
        row_id = self._seed("a")
        accessor = IntegrationManager.github.oauth

        accessor.get(TEAM, row_id)
        accessor.get(TEAM, row_id)
        assert len(self._calls("/resolve")) == 1

        # A write in another process is not seen until the entry expires.
        self.fake.update(_every_row(TEAM)[0], team_id=TEAM, id=row_id, patch=IntegrationPatch(errors="elsewhere"))
        assert accessor.get(TEAM, row_id).errors == ""
        self.offset += 61
        assert accessor.get(TEAM, row_id).errors == "elsewhere"

        # A write in this process is seen at once.
        accessor.update(TEAM, row_id, errors="here")
        assert accessor.get(TEAM, row_id).errors == "here"

    def test_list_reads_secrets_again_when_the_cached_resolve_is_older_than_the_row(self) -> None:
        row_id = self._seed("a")
        accessor = IntegrationManager.github.oauth
        accessor.get(TEAM, row_id)

        # Another process changes the row, so the listed version is newer than the cached one.
        patch = IntegrationPatch(errors="elsewhere", sensitive_config_patch={"access_token": "new"})
        self.fake.update(_every_row(TEAM)[0], team_id=TEAM, id=row_id, patch=patch)
        self.stub._bump(row_id)

        [record] = accessor.list(TEAM)
        assert (record.errors, record.access_token) == ("elsewhere", "new")

    def test_a_resolve_that_started_before_an_invalidation_is_not_cached(self) -> None:
        row_id = self._seed("a")
        stub = self.stub

        class InvalidatingSession:
            # A write in another thread of this process lands while the resolve is in flight.
            def request(self, method: str, url: str, *args: Any, **kwargs: Any) -> Any:
                response = stub.request(method, url, *args, **kwargs)
                if url.endswith("/resolve"):
                    backend._cache.invalidate(TEAM, str(row_id))
                return response

        backend = self._use(InvalidatingSession())
        IntegrationManager.github.oauth.get(TEAM, row_id)
        IntegrationManager.github.oauth.get(TEAM, row_id)

        assert len(self._calls("/resolve")) == 2

    @parameterized.expand(
        [
            ("token_expires_before_the_ttl", 10, 11, 2),
            ("token_expires_after_the_ttl", 3600, 30, 1),
            ("token_already_expired", -5, 0, 2),
        ]
    )
    def test_resolve_cache_never_outlives_the_access_token(
        self, _name: str, expires_in: int, advance: int, resolves: int
    ) -> None:
        row_id = self._seed("a", refreshed_at=int(time.time()), expires_in=expires_in)

        IntegrationManager.github.oauth.get(TEAM, row_id)
        self.offset += advance
        IntegrationManager.github.oauth.get(TEAM, row_id)

        assert len(self._calls("/resolve")) == resolves

    def test_reads_follow_every_page(self) -> None:
        ids = [self._seed(f"r{n}") for n in range(5)]

        with patch.object(service_backend, "PAGE_SIZE", 2):
            rows = IntegrationManager.github.oauth.list(TEAM)
            count = IntegrationManager.github.oauth.count_by_external_id("r1")

        assert ([row.id for row in rows], count) == (ids, 1)
        assert len(self._calls("")) - len(self._calls("/")) == 3

    def test_list_across_teams_orders_by_id_and_pages_with_after_id(self) -> None:
        first, second, third = (
            self._seed(name, team_id=team) for name, team in (("a", TEAM), ("b", OTHER_TEAM), ("c", TEAM))
        )
        # The service pages by `created_at`. Make that order differ from the id order.
        latest = max(row.created_at for row in self.fake._rows.values())
        self.fake._rows[first] = replace(self.fake._rows[first], created_at=latest + timedelta(seconds=1))
        accessor = IntegrationManager.github.oauth

        with patch.object(service_backend, "PAGE_SIZE", 1):
            every_row = accessor.list_across_teams(CrossTeamFilter())
            next_page = accessor.list_across_teams(CrossTeamFilter(after_id=first, limit=1))
            newest_first = accessor.list_across_teams(CrossTeamFilter(newest_first=True, after_id=third))

        assert [row.id for row in every_row] == [first, second, third]
        assert [row.id for row in next_page] == [second]
        assert [row.id for row in newest_first] == [second, first]
        # The service returns no secrets from a read across teams.
        with self.assertRaises(IntegrationServiceError) as raised:
            _ = every_row[0].access_token
        assert raised.exception.code == "secrets_withheld"

    @parameterized.expand(
        [
            ("every_row_in_scope_uses_the_bulk_route", "oauth", True),
            ("rows_of_another_auth_type_are_written_one_by_one", "token", False),
        ]
    )
    def test_writes_by_external_id_stay_in_the_auth_type_of_the_accessor(
        self, _name: str, other_auth_type: str, bulk: bool
    ) -> None:
        own = self._seed("shared")
        other = self._seed(
            "shared", team_id=OTHER_TEAM, **({"auth_type": "token"} if other_auth_type == "token" else {})
        )
        accessor = IntegrationManager.github.oauth

        updated = accessor.update_by_external_id("shared", IntegrationPatch(errors="SUSPENDED"))

        errors = {row.id: row.errors for row in self.fake.list_across_teams(_every_row(TEAM)[0], CrossTeamFilter())}
        assert updated == (2 if bulk else 1)
        assert errors == {own: "SUSPENDED", other: "SUSPENDED" if bulk else ""}
        assert (("PATCH", "/by-external-id/github/shared") in self._calls()) is bulk

        deleted = accessor.delete_by_external_id("shared")

        remaining = [row.id for row in self.fake.list_across_teams(_every_row(TEAM)[0], CrossTeamFilter())]
        assert (deleted, remaining) == ((2, []) if bulk else (1, [other]))

    @parameterized.expand(
        [
            ("change_external_id", lambda: IntegrationManager.github.oauth.change_external_id(TEAM, 1, "b")),
            ("refresh_access_token", lambda: IntegrationManager.resend.oauth.refresh_access_token(TEAM, 1)),
        ]
    )
    def test_operations_without_a_route_raise(self, _name: str, action: Callable[[], Any]) -> None:
        with self.assertRaises(NotImplementedError):
            action()

        assert self.stub.calls == []


class TestConfiguredBackend(SimpleTestCase):
    @parameterized.expand([("django", DjangoBackend), ("service", ServiceBackend), ("other", None)])
    def test_the_setting_chooses_the_backend(self, name: str, expected: type | None) -> None:
        with override_settings(INTEGRATIONS_STORAGE_BACKEND=name):
            if expected is None:
                with self.assertRaises(ImproperlyConfigured):
                    configured_backend()
            else:
                assert type(configured_backend()) is expected


def _every_row(team_id: int) -> tuple[RowScope, RowFilter]:
    return RowScope(kinds=None, source_rows=SourceRows.INCLUDE), RowFilter(team_id=team_id)
