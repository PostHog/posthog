import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from temporalio.testing import ActivityEnvironment

from posthog.temporal.signup_enrichment.workflow import SignupEnrichmentInputs, enrich_signup_organization_activity

from products.growth.backend.enrichment.fields import EnrichmentFields

pytestmark = pytest.mark.asyncio

_MODULE = "posthog.temporal.signup_enrichment.workflow"
_INPUTS = SignupEnrichmentInputs(organization_id="org-1", distinct_id="d1", domain="stripe.com")


def _patches(*, enrich_return, deterministic=None):
    pha_client = MagicMock()
    return pha_client, (
        patch(f"{_MODULE}.get_client", return_value=pha_client),
        patch(f"{_MODULE}.enrich_organization", AsyncMock(**enrich_return)),
        patch(f"{_MODULE}._deterministic_company_type", return_value=deterministic),
        patch(f"{_MODULE}.capture_signup_enrichment_snapshot"),
    )


async def test_emits_success_signal_and_snapshot_on_match():
    fields = EnrichmentFields(company_type="STARTUP", headcount=130, industry="Fintech")
    pha_client, (get_client, enrich, det, snapshot) = _patches(enrich_return={"return_value": fields})
    with get_client, enrich, det, snapshot as snapshot_mock:
        result = await ActivityEnvironment().run(enrich_signup_organization_activity, _INPUTS)

    assert result == {"matched": True, "fields_filled": 3}
    # Snapshot captured once, built from the enriched fields.
    snapshot_mock.assert_called_once()
    assert snapshot_mock.call_args.kwargs["snapshot"].company_type == "STARTUP"
    # Launch signal emitted with success + the filled field keys.
    signal = next(c for c in pha_client.capture.call_args_list if c.kwargs["event"] == "signup_enrichment_completed")
    assert signal.kwargs["properties"]["success"] is True
    assert signal.kwargs["properties"]["matched"] is True


async def test_falls_back_to_deterministic_company_type_on_miss():
    pha_client, (get_client, enrich, det, snapshot) = _patches(enrich_return={"return_value": None}, deterministic="yc")
    with get_client, enrich, det, snapshot as snapshot_mock:
        result = await ActivityEnvironment().run(enrich_signup_organization_activity, _INPUTS)

    assert result == {"matched": False, "fields_filled": 0}
    assert snapshot_mock.call_args.kwargs["snapshot"].company_type == "yc"


async def test_failure_emits_failure_signal_and_reraises():
    pha_client, (get_client, enrich, det, snapshot) = _patches(enrich_return={"side_effect": RuntimeError("boom")})
    with get_client, enrich, det, snapshot, pytest.raises(RuntimeError):
        await ActivityEnvironment().run(enrich_signup_organization_activity, _INPUTS)

    signal = next(c for c in pha_client.capture.call_args_list if c.kwargs["event"] == "signup_enrichment_completed")
    assert signal.kwargs["properties"]["success"] is False
    assert signal.kwargs["properties"]["error"] == "RuntimeError"
