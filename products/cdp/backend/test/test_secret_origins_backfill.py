from collections import Counter
from io import StringIO
from typing import Any

from posthog.test.base import BaseTest

from django.core.management import call_command
from django.db import connection

from posthog.helpers.encrypted_fields import FERNET_TOKEN_PREFIX

from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.cdp.backend.services.secret_origins_backfill import (
    apply_secret_origins,
    backfill_secret_origins,
    plan_secret_origins,
)

LIVE_HOG = "fetch('https://api.example.com/track', {'headers': {'Authorization': inputs.api_key}})"
DRAFT_HOG = "fetch('https://eu.example.com/track', {'headers': {'Authorization': inputs.api_key}})"
EVENT_URL_HOG = "fetch(inputs.url, {'headers': {'Authorization': inputs.api_key}})"
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

    def test_binds_live_and_staged_secrets_once_and_never_changes_values(self) -> None:
        live = self._function(
            LIVE_HOG, {"api_key": {"value": "secret-live"}, "token": KEPT_TOKEN}, enabled=True, template_id="template-a"
        )
        HogFunction.objects.filter(pk=live.pk).update(
            draft={"hog": DRAFT_HOG}, draft_encrypted_inputs={"api_key": {"value": "secret-draft"}}
        )
        disabled = self._function(
            EVENT_URL_HOG,
            {"api_key": {"value": "secret-disabled"}, "unused": {"value": "secret-unused"}},
            inputs={"url": {"value": "{event.properties.url}"}},
            template_id="template-webhook",
        )
        self._function(LIVE_HOG, {"api_key": {"value": "secret-deleted"}}, deleted=True)
        self._function("export function onLoad() {}", {"api_key": {"value": "secret-site"}}, type="site_destination")
        before = self._stored()

        out = StringIO()
        call_command("backfill_secret_origins", "--team-id", str(self.team.pk), stdout=out)
        assert self._stored() == before
        assert "template-webhook=1" in out.getvalue()
        assert "secret-" not in out.getvalue() and "example.com" not in out.getvalue()

        report = backfill_secret_origins(apply=True, team_id=self.team.pk)
        assert report.outcomes == Counter(
            {
                ("live", "bound"): 1,
                ("live", "already_bound"): 1,
                ("live", "unbound"): 1,
                ("live", "empty"): 1,
                ("staged", "bound"): 1,
            }
        )
        assert report.unbound_templates == Counter({"template-webhook": 1})
        assert report.rows_written == 2

        live.refresh_from_db()
        assert live.encrypted_inputs == {
            "api_key": {"value": "secret-live", "allowed_origins": ["https://api.example.com"]},
            "token": KEPT_TOKEN,
        }
        assert live.draft_encrypted_inputs == {
            "api_key": {"value": "secret-draft", "allowed_origins": ["https://eu.example.com"]}
        }
        disabled.refresh_from_db()
        assert disabled.encrypted_inputs == {
            "api_key": {"value": "secret-disabled", "allowed_origins": "*"},
            "unused": {"value": "secret-unused", "allowed_origins": []},
        }
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT encrypted_inputs, draft_encrypted_inputs FROM posthog_hogfunction WHERE id = %s", [live.pk]
            )
            assert all(column.startswith(FERNET_TOKEN_PREFIX) for column in cursor.fetchone())
        after = self._stored()
        assert {pk: after[pk] for pk in after if pk not in (live.pk, disabled.pk)} == {
            pk: before[pk] for pk in before if pk not in (live.pk, disabled.pk)
        }

        rerun = backfill_secret_origins(apply=True, team_id=self.team.pk)
        assert rerun.outcomes == Counter({("live", "already_bound"): 4, ("staged", "already_bound"): 1})
        assert rerun.rows_written == 0
        assert self._stored() == after

    def test_skips_a_row_saved_after_the_scan(self) -> None:
        hog_function = self._function(LIVE_HOG, {"api_key": {"value": "secret-live"}})
        plan = plan_secret_origins(HogFunction.objects.get(pk=hog_function.pk))
        HogFunction.objects.filter(pk=hog_function.pk).update(hog=DRAFT_HOG)

        assert apply_secret_origins(plan) is False

        hog_function.refresh_from_db()
        assert hog_function.encrypted_inputs == {"api_key": {"value": "secret-live"}}
