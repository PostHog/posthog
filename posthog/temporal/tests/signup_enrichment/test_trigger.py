from unittest.mock import patch

from django.test import override_settings

from posthog.temporal.signup_enrichment.trigger import start_signup_enrichment_workflow


def _dispatch_mocks(region="US"):
    """Patch out the transaction/Temporal boundary so on_commit fires inline."""
    return (
        patch("posthog.temporal.signup_enrichment.trigger.transaction.on_commit", side_effect=lambda fn: fn()),
        patch("posthog.temporal.signup_enrichment.trigger.sync_connect"),
        patch("posthog.temporal.signup_enrichment.trigger.asyncio.run"),
        patch("posthog.temporal.signup_enrichment.trigger.get_instance_region", return_value=region),
    )


@override_settings(GROWTH_SIGNUP_ENRICHMENT_ENABLED=True, HARMONIC_API_KEY="key")
def test_dispatches_for_work_email_in_us():
    on_commit, connect, run, region = _dispatch_mocks()
    with on_commit, connect as connect_mock, run, region:
        start_signup_enrichment_workflow(organization_id="org-1", distinct_id="d1", email="founder@stripe.com")
    connect_mock.assert_called_once()


@override_settings(GROWTH_SIGNUP_ENRICHMENT_ENABLED=False, HARMONIC_API_KEY="key")
def test_kill_switch_off_never_dispatches():
    on_commit, connect, run, region = _dispatch_mocks()
    with on_commit, connect as connect_mock, run, region:
        start_signup_enrichment_workflow(organization_id="org-1", distinct_id="d1", email="founder@stripe.com")
    connect_mock.assert_not_called()


@override_settings(GROWTH_SIGNUP_ENRICHMENT_ENABLED=True, HARMONIC_API_KEY="")
def test_missing_harmonic_key_never_dispatches():
    on_commit, connect, run, region = _dispatch_mocks()
    with on_commit, connect as connect_mock, run, region:
        start_signup_enrichment_workflow(organization_id="org-1", distinct_id="d1", email="founder@stripe.com")
    connect_mock.assert_not_called()


@override_settings(GROWTH_SIGNUP_ENRICHMENT_ENABLED=True, HARMONIC_API_KEY="key")
def test_non_us_region_never_dispatches():
    on_commit, connect, run, region = _dispatch_mocks(region="EU")
    with on_commit, connect as connect_mock, run, region:
        start_signup_enrichment_workflow(organization_id="org-1", distinct_id="d1", email="founder@stripe.com")
    connect_mock.assert_not_called()


@override_settings(GROWTH_SIGNUP_ENRICHMENT_ENABLED=True, HARMONIC_API_KEY="key")
def test_personal_email_domain_is_skipped():
    on_commit, connect, run, region = _dispatch_mocks()
    with on_commit, connect as connect_mock, run, region:
        start_signup_enrichment_workflow(organization_id="org-1", distinct_id="d1", email="someone@gmail.com")
    connect_mock.assert_not_called()
