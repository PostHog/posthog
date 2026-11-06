from collections import Counter
from collections.abc import Callable
from io import StringIO
from typing import Any

import pytest
from posthog.test.base import BaseTest

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection

from parameterized import parameterized

from posthog.helpers.encrypted_fields import FERNET_TOKEN_PREFIX

from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.cdp.backend.services.secret_origins_backfill import (
    SecretOutcome,
    backfill_secret_origins,
    commit_secret_origins,
)

LIVE_HOG = "fetch('https://api.example.com/track', {'headers': {'Authorization': inputs.api_key}})"
MOVED_HOG = "fetch('https://eu.example.com/track', {'headers': {'Authorization': inputs.api_key}})"
EVENT_URL_HOG = "fetch(inputs.url, {'headers': {'Authorization': inputs.api_key, 'X-Token': inputs.token}})"
EVENT_URL_INPUTS = {"url": {"value": "{event.properties.url}"}}
KEPT_TOKEN = {"value": "secret-token", "allowed_origins": ["https://kept.example.com"]}


class TestSecretOriginsBackfill(BaseTest):
    def _function(
        self, hog: str, secrets: dict[str, Any], inputs: dict[str, Any] | None = None, **fields: Any
    ) -> HogFunction:
        schema = [{"key": key, "type": "string", "label": key, "secret": True} for key in secrets]
        schema += [{"key": key, "type": "string", "label": key} for key in inputs or {}]
        return HogFunction.objects.create(
            team=self.team,
            name="destination",
            hog=hog,
            inputs_schema=schema,
            inputs=inputs or {},
            encrypted_inputs=secrets,
            **{"type": "destination", **fields},
        )

    def _stored(self) -> dict[Any, tuple]:
        return {
            hog_function.pk: (hog_function.encrypted_inputs, hog_function.draft_encrypted_inputs)
            for hog_function in HogFunction.objects.filter(team=self.team)
        }

    def _commit(self) -> Any:
        return backfill_secret_origins(commit=True, team_id=self.team.pk, batch_size=1)

    @parameterized.expand(
        [
            (
                "fixed_host",
                LIVE_HOG,
                {
                    "api_key": {"value": "secret-live"},
                    "token": KEPT_TOKEN,
                    "legacy": {"value": "secret-legacy", "allowed_origins": None},
                },
                {},
                {
                    "api_key": {"value": "secret-live", "allowed_origins": ["https://api.example.com"]},
                    "token": KEPT_TOKEN,
                    "legacy": {"value": "secret-legacy", "allowed_origins": []},
                },
                {SecretOutcome.BOUND: 1, SecretOutcome.ALREADY_BOUND: 1, SecretOutcome.EMPTY: 1},
            ),
            (
                "url_from_event",
                EVENT_URL_HOG,
                {"api_key": {"value": "secret-a"}, "token": {"value": "secret-b"}, "unused": {"value": "secret-c"}},
                EVENT_URL_INPUTS,
                {
                    "api_key": {"value": "secret-a", "allowed_origins": "*"},
                    "token": {"value": "secret-b", "allowed_origins": "*"},
                    "unused": {"value": "secret-c", "allowed_origins": []},
                },
                {SecretOutcome.UNBOUND: 2, SecretOutcome.EMPTY: 1},
            ),
        ]
    )
    def test_commit_binds_each_unbound_secret_and_keeps_its_value(
        self,
        _name: str,
        hog: str,
        secrets: dict[str, Any],
        inputs: dict[str, Any],
        expected: dict[str, Any],
        expected_outcomes: dict[SecretOutcome, int],
    ) -> None:
        hog_function = self._function(hog, secrets, inputs)

        report = self._commit()

        hog_function.refresh_from_db()
        assert hog_function.encrypted_inputs == expected
        assert report.outcomes == Counter(expected_outcomes)
        assert (report.rows_written, report.rows_failed) == (1, 0)

    @parameterized.expand(
        [
            (
                "no_encrypted_inputs",
                {"value": "secret-legacy"},
                None,
                {"value": "secret-legacy", "allowed_origins": ["https://api.example.com"]},
            ),
            (
                "beside_an_encrypted_secret",
                {"value": "secret-legacy"},
                {"token": KEPT_TOKEN},
                {"value": "secret-legacy", "allowed_origins": ["https://api.example.com"]},
            ),
            ("already_bound", KEPT_TOKEN, None, KEPT_TOKEN),
        ]
    )
    def test_commit_moves_a_plaintext_secret_into_the_encrypted_column_and_binds_it(
        self,
        _name: str,
        plaintext: dict[str, Any],
        stored_secrets: dict[str, Any] | None,
        expected_secret: dict[str, Any],
    ) -> None:
        hog_function = self._function(LIVE_HOG, {"api_key": plaintext, **(stored_secrets or {})})
        HogFunction.objects.filter(pk=hog_function.pk).update(
            inputs={"api_key": plaintext}, encrypted_inputs=stored_secrets
        )

        report = self._commit()

        hog_function.refresh_from_db()
        assert hog_function.inputs == {}
        assert hog_function.encrypted_inputs == {**(stored_secrets or {}), "api_key": expected_secret}
        assert (report.rows_written, report.rows_failed) == (1, 0)

    def test_skips_a_row_whose_encrypted_inputs_no_key_decrypts(self) -> None:
        hog_function = self._function(LIVE_HOG, {"api_key": {"value": "secret-legacy"}})
        HogFunction.objects.filter(pk=hog_function.pk).update(inputs={"api_key": {"value": "secret-legacy"}})
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE posthog_hogfunction SET encrypted_inputs = %s WHERE id = %s",
                [f"{FERNET_TOKEN_PREFIX}undecryptable", hog_function.pk],
            )
        before = self._stored()

        report = self._commit()

        assert self._stored() == before
        assert report.outcomes == Counter({SecretOutcome.SKIPPED: 1})
        assert (report.rows_written, report.rows_failed) == (0, 0)

    def test_commit_writes_only_the_encrypted_column_as_ciphertext(self) -> None:
        hog_function = self._function(LIVE_HOG, {"api_key": {"value": "secret-live"}}, enabled=True)
        hog_function.refresh_from_db()
        updated_at = hog_function.updated_at

        self._commit()

        hog_function.refresh_from_db()
        assert hog_function.updated_at == updated_at
        with connection.cursor() as cursor:
            cursor.execute("SELECT encrypted_inputs FROM posthog_hogfunction WHERE id = %s", [hog_function.pk])
            assert cursor.fetchone()[0].startswith(FERNET_TOKEN_PREFIX)

    def test_dry_run_writes_nothing_and_prints_no_secret_or_host(self) -> None:
        self._function(LIVE_HOG, {"api_key": {"value": "secret-live"}})
        self._function(EVENT_URL_HOG, {"api_key": {"value": "secret-a"}}, EVENT_URL_INPUTS, template_id="template-hook")
        plaintext = self._function(LIVE_HOG, {"api_key": {"value": "secret-legacy"}})
        HogFunction.objects.filter(pk=plaintext.pk).update(
            inputs={"api_key": {"value": "secret-legacy"}}, encrypted_inputs=None
        )
        before = self._stored()

        out = StringIO()
        call_command("backfill_secret_origins", "--team-id", str(self.team.pk), stdout=out)

        assert self._stored() == before
        plaintext.refresh_from_db()
        assert plaintext.inputs == {"api_key": {"value": "secret-legacy"}}
        assert "rows to write: 3" in out.getvalue()
        assert "template-hook=1" in out.getvalue()
        assert "secret-" not in out.getvalue() and "example.com" not in out.getvalue()

    @parameterized.expand(
        [
            ("deleted", {"deleted": True}),
            ("site_destination", {"type": "site_destination", "hog": "export function onLoad() {}"}),
        ]
    )
    def test_leaves_out_of_scope_rows_untouched(self, _name: str, fields: dict[str, Any]) -> None:
        self._function(**{"hog": LIVE_HOG, "secrets": {"api_key": {"value": "secret-live"}}, **fields})
        before = self._stored()

        report = self._commit()

        assert self._stored() == before
        assert report.outcomes == Counter()

    def test_leaves_a_staged_draft_secret_untouched(self) -> None:
        hog_function = self._function(LIVE_HOG, {"api_key": {"value": "secret-live"}})
        staged = {"api_key": {"value": "secret-draft"}}
        HogFunction.objects.filter(pk=hog_function.pk).update(draft={"hog": MOVED_HOG}, draft_encrypted_inputs=staged)

        self._commit()

        hog_function.refresh_from_db()
        assert hog_function.draft_encrypted_inputs == staged

    def test_rerun_changes_nothing_and_still_lists_unbound_functions(self) -> None:
        self._function(LIVE_HOG, {"api_key": {"value": "secret-live"}})
        self._function(EVENT_URL_HOG, {"api_key": {"value": "secret-a"}}, EVENT_URL_INPUTS, template_id="template-hook")
        self._commit()
        after = self._stored()

        rerun = self._commit()
        dry_run = backfill_secret_origins(commit=False, team_id=self.team.pk)

        assert self._stored() == after
        assert rerun.outcomes == Counter({SecretOutcome.ALREADY_BOUND: 2})
        assert rerun.unbound_templates == Counter({"template-hook": 1})
        assert (dry_run.rows_to_write, rerun.rows_written) == (0, 0)

    def test_a_failed_row_fails_the_command_after_the_other_rows_are_written(self) -> None:
        broken = self._function(LIVE_HOG, {"api_key": {"value": "secret-broken"}})
        HogFunction.objects.filter(pk=broken.pk).update(inputs=["not", "a", "dict"])
        healthy = self._function(LIVE_HOG, {"api_key": {"value": "secret-live"}})

        out = StringIO()
        with pytest.raises(CommandError):
            call_command(
                "backfill_secret_origins", "--commit", "--team-id", str(self.team.pk), "--batch-size", "1", stdout=out
            )

        healthy.refresh_from_db()
        assert healthy.encrypted_inputs["api_key"]["allowed_origins"] == ["https://api.example.com"]
        assert "rows that failed: 1" in out.getvalue()

    @parameterized.expand(
        [
            ("saved", lambda rows: rows.update(hog=MOVED_HOG), ["https://eu.example.com"]),
            ("soft_deleted", lambda rows: rows.update(deleted=True), None),
        ]
    )
    def test_commit_plans_the_row_as_it_is_when_locked(
        self, _name: str, change: Callable[[Any], Any], expected_origins: list[str] | None
    ) -> None:
        hog_function = self._function(LIVE_HOG, {"api_key": {"value": "secret-live"}})
        rows = HogFunction.objects.filter(pk=hog_function.pk)
        change(rows)

        plan = commit_secret_origins(hog_function.pk, self.team.pk)

        assert (plan is None) == (expected_origins is None)
        assert rows.get().encrypted_inputs["api_key"].get("allowed_origins") == expected_origins
