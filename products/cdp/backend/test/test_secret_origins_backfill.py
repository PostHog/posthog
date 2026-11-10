from collections import Counter
from collections.abc import Callable
from io import StringIO
from typing import Any, Optional

import pytest
from posthog.test.base import BaseTest

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection

from parameterized import parameterized

from posthog.helpers.encrypted_fields import FERNET_TOKEN_PREFIX

from products.cdp.backend.api.test.test_hog_function_templates import MOCK_NODE_TEMPLATES
from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.cdp.backend.services.secret_origins_backfill import (
    SecretOutcome,
    TemplateCache,
    backfill_secret_origins,
    commit_secret_origins,
)
from products.cdp.backend.templates.hog_function_template import sync_template_to_db

HOG = "fetch(inputs.url, {'headers': {'Authorization': inputs.api_key}})"
URL_INPUTS = {"url": {"value": "https://api.example.com/track"}}
DECLARED = {"scheme": "bearer", "origins": ["https://api.example.com"]}
FROM_URL = {"scheme": "bearer", "origin_input": "url"}
KEPT_TOKEN = {"value": "secret-token", "allowed_origins": ["https://kept.example.com"]}
BOUND_TOKEN = {"value": "secret-bound", "auth": {"scheme": "bearer", "origins": ["https://api.example.com"]}}


class TestSecretOriginsBackfill(BaseTest):
    def _template(self, template_id: str, auth: Optional[dict]) -> None:
        api_key = {"key": "api_key", "type": "string", "label": "API key", "secret": True}
        sync_template_to_db(
            {
                **MOCK_NODE_TEMPLATES[0],
                "id": template_id,
                "inputs_schema": [
                    {"key": "url", "type": "string", "label": "URL"},
                    {**api_key, **({"auth": auth} if auth else {})},
                ],
            }
        )

    def _function(
        self,
        secrets: dict[str, Any],
        inputs: Optional[dict[str, Any]] = None,
        template_id: Optional[str] = None,
        **fields: Any,
    ) -> HogFunction:
        schema = [{"key": key, "type": "string", "label": key, "secret": True} for key in secrets]
        schema += [{"key": key, "type": "string", "label": key} for key in inputs or {}]
        return HogFunction.objects.create(
            team=self.team,
            name="destination",
            template_id=template_id,
            inputs_schema=schema,
            inputs=inputs or {},
            encrypted_inputs=secrets,
            **{"type": "destination", "hog": HOG, **fields},
        )

    def _stored(self) -> dict[Any, tuple]:
        return {
            hog_function.pk: (hog_function.inputs, hog_function.encrypted_inputs, hog_function.draft_encrypted_inputs)
            for hog_function in HogFunction.objects.filter(team=self.team)
        }

    def _commit(self) -> Any:
        return backfill_secret_origins(commit=True, team_id=self.team.pk, batch_size=1)

    @parameterized.expand(
        [
            (
                "declared_origins",
                DECLARED,
                URL_INPUTS,
                ["https://api.example.com"],
                SecretOutcome.DECLARED,
            ),
            (
                "origin_of_the_url_input",
                FROM_URL,
                {"url": {"value": "https://eu.example.com/track"}},
                ["https://eu.example.com"],
                SecretOutcome.DECLARED,
            ),
            (
                "templated_url_input",
                FROM_URL,
                {"url": {"value": "{event.properties.url}"}},
                "*",
                SecretOutcome.ANY_ORIGIN,
            ),
            ("no_declaration", None, URL_INPUTS, "*", SecretOutcome.ANY_ORIGIN),
        ]
    )
    def test_commit_stores_the_template_declared_origins_and_keeps_each_value(
        self,
        _name: str,
        auth: Optional[dict],
        inputs: dict[str, Any],
        expected_origins: list[str] | str,
        expected_outcome: SecretOutcome,
    ) -> None:
        self._template("template-sender", auth)
        secrets = {
            "api_key": {"value": "secret-live"},
            "token": KEPT_TOKEN,
            "bound": BOUND_TOKEN,
            "legacy": {"value": "secret-legacy", "allowed_origins": None},
        }
        hog_function = self._function(secrets, inputs, template_id="template-sender")

        report = self._commit()

        hog_function.refresh_from_db()
        assert hog_function.encrypted_inputs == {
            "api_key": {"value": "secret-live", "allowed_origins": expected_origins},
            "token": KEPT_TOKEN,
            "bound": BOUND_TOKEN,
            "legacy": {"value": "secret-legacy", "allowed_origins": "*"},
        }
        assert report.outcomes == Counter(
            [expected_outcome, SecretOutcome.ALREADY_STORED, SecretOutcome.PLATFORM_AUTH, SecretOutcome.ANY_ORIGIN]
        )
        assert (report.rows_written, report.rows_failed) == (1, 0)

    def test_function_with_only_bound_stored_or_undeclared_secrets_is_not_written(self) -> None:
        hog_function = self._function({"bound": BOUND_TOKEN, "token": KEPT_TOKEN})
        HogFunction.objects.filter(pk=hog_function.pk).update(
            encrypted_inputs={"bound": BOUND_TOKEN, "token": KEPT_TOKEN, "orphan": {"value": "secret-orphan"}}
        )
        before = self._stored()

        report = self._commit()

        assert self._stored() == before
        assert report.outcomes == Counter([SecretOutcome.PLATFORM_AUTH, SecretOutcome.ALREADY_STORED])
        assert report.rows_written == 0

    @parameterized.expand(
        [
            ("unstored", {"value": "secret-legacy"}, None, {"value": "secret-legacy", "allowed_origins": "*"}),
            ("beside_an_encrypted_secret", {"value": "secret-legacy"}, {"token": KEPT_TOKEN}, None),
            ("already_stored", KEPT_TOKEN, None, KEPT_TOKEN),
            (
                "stale_beside_its_encrypted_copy",
                {"value": "secret-old"},
                {"api_key": {"value": "secret-live"}},
                {"value": "secret-live", "allowed_origins": "*"},
            ),
        ]
    )
    def test_commit_moves_a_plaintext_secret_into_the_encrypted_column(
        self,
        _name: str,
        plaintext: dict[str, Any],
        stored_secrets: Optional[dict[str, Any]],
        expected_secret: Optional[dict[str, Any]],
    ) -> None:
        hog_function = self._function({"api_key": plaintext, **(stored_secrets or {})})
        url = {"value": "https://api.example.com/track", "bytecode": ["_H", 1, 32, "url"], "order": 0}
        HogFunction.objects.filter(pk=hog_function.pk).update(
            inputs={"api_key": plaintext, "url": url}, encrypted_inputs=stored_secrets
        )
        updated_at = HogFunction.objects.get(pk=hog_function.pk).updated_at

        report = self._commit()

        hog_function.refresh_from_db()
        assert (hog_function.inputs, hog_function.updated_at) == ({"url": url}, updated_at)
        assert hog_function.encrypted_inputs == {
            **(stored_secrets or {}),
            "api_key": expected_secret or {**plaintext, "allowed_origins": "*"},
        }
        assert (report.rows_written, report.rows_failed) == (1, 0)

    def test_origin_input_left_to_its_default_resolves_as_a_save_resolves_it(self) -> None:
        self._template("template-sender", FROM_URL)
        hog_function = self._function({"api_key": {"value": "secret-live"}}, template_id="template-sender")
        url_schema = {"key": "url", "type": "string", "label": "URL", "required": True}
        HogFunction.objects.filter(pk=hog_function.pk).update(
            inputs_schema=[
                *(hog_function.inputs_schema or []),
                {**url_schema, "default": "https://eu.example.com/track"},
            ]
        )

        self._commit()

        hog_function.refresh_from_db()
        assert hog_function.encrypted_inputs["api_key"]["allowed_origins"] == ["https://eu.example.com"]

    def test_skips_a_row_whose_encrypted_inputs_no_key_decrypts(self) -> None:
        hog_function = self._function({"api_key": {"value": "secret-legacy"}})
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
        hog_function = self._function({"api_key": {"value": "secret-live"}}, enabled=True)
        hog_function.refresh_from_db()
        updated_at = hog_function.updated_at

        self._commit()

        hog_function.refresh_from_db()
        assert hog_function.updated_at == updated_at
        with connection.cursor() as cursor:
            cursor.execute("SELECT encrypted_inputs FROM posthog_hogfunction WHERE id = %s", [hog_function.pk])
            assert cursor.fetchone()[0].startswith(FERNET_TOKEN_PREFIX)

    def test_dry_run_writes_nothing_and_prints_no_secret_or_host(self) -> None:
        self._template("template-sender", DECLARED)
        self._function({"api_key": {"value": "secret-live"}}, URL_INPUTS, template_id="template-sender")
        self._function({"api_key": {"value": "secret-a"}}, URL_INPUTS, template_id="template-hook")
        plaintext = self._function({"api_key": {"value": "secret-legacy"}})
        HogFunction.objects.filter(pk=plaintext.pk).update(
            inputs={"api_key": {"value": "secret-legacy"}}, encrypted_inputs=None
        )
        before = self._stored()

        out = StringIO()
        call_command("backfill_secret_origins", "--team-id", str(self.team.pk), stdout=out)

        assert self._stored() == before
        assert "rows to write: 3" in out.getvalue()
        assert "secrets declared: 1" in out.getvalue() and "secrets any_origin: 2" in out.getvalue()
        assert "template-hook=1" in out.getvalue() and "template-sender" not in out.getvalue()
        assert "secret-" not in out.getvalue() and "example.com" not in out.getvalue()

    @parameterized.expand(
        [
            ("deleted", {"deleted": True}),
            ("site_destination", {"type": "site_destination", "hog": "export function onLoad() {}"}),
        ]
    )
    def test_leaves_out_of_scope_rows_untouched(self, _name: str, fields: dict[str, Any]) -> None:
        self._function({"api_key": {"value": "secret-live"}}, **fields)
        before = self._stored()

        report = self._commit()

        assert self._stored() == before
        assert report.outcomes == Counter()

    def test_leaves_a_staged_draft_secret_untouched(self) -> None:
        hog_function = self._function({"api_key": {"value": "secret-live"}})
        staged = {"api_key": {"value": "secret-draft"}}
        HogFunction.objects.filter(pk=hog_function.pk).update(draft={"hog": "return"}, draft_encrypted_inputs=staged)

        self._commit()

        hog_function.refresh_from_db()
        assert hog_function.draft_encrypted_inputs == staged

    def test_rerun_changes_nothing_and_still_lists_functions_open_to_any_origin(self) -> None:
        self._template("template-sender", DECLARED)
        self._function({"api_key": {"value": "secret-live"}}, URL_INPUTS, template_id="template-sender")
        self._function({"api_key": {"value": "secret-a"}}, URL_INPUTS, template_id="template-hook")
        self._commit()
        after = self._stored()

        rerun = self._commit()
        dry_run = backfill_secret_origins(commit=False, team_id=self.team.pk)

        assert self._stored() == after
        assert rerun.outcomes == Counter({SecretOutcome.ALREADY_STORED: 2})
        assert rerun.any_origin_templates == Counter({"template-hook": 1})
        assert (dry_run.rows_to_write, rerun.rows_written) == (0, 0)

    def test_a_failed_row_fails_the_command_after_the_other_rows_are_written(self) -> None:
        broken = self._function({"api_key": {"value": "secret-broken"}})
        HogFunction.objects.filter(pk=broken.pk).update(inputs=["not", "a", "dict"])
        healthy = self._function({"api_key": {"value": "secret-live"}})

        out = StringIO()
        with pytest.raises(CommandError):
            call_command(
                "backfill_secret_origins", "--commit", "--team-id", str(self.team.pk), "--batch-size", "1", stdout=out
            )

        healthy.refresh_from_db()
        assert healthy.encrypted_inputs["api_key"]["allowed_origins"] == "*"
        assert "rows that failed: 1" in out.getvalue()

    @parameterized.expand(
        [
            (
                "saved",
                lambda rows: rows.update(inputs={"url": {"value": "https://eu.example.com/a"}}),
                ["https://eu.example.com"],
            ),
            ("soft_deleted", lambda rows: rows.update(deleted=True), None),
        ]
    )
    def test_commit_plans_the_row_as_it_is_when_locked(
        self, _name: str, change: Callable[[Any], Any], expected_origins: Optional[list[str]]
    ) -> None:
        self._template("template-sender", FROM_URL)
        hog_function = self._function({"api_key": {"value": "secret-live"}}, URL_INPUTS, template_id="template-sender")
        rows = HogFunction.objects.filter(pk=hog_function.pk)
        change(rows)

        plan = commit_secret_origins(hog_function.pk, self.team.pk, TemplateCache())

        assert (plan is None) == (expected_origins is None)
        assert rows.get().encrypted_inputs["api_key"].get("allowed_origins") == expected_origins
