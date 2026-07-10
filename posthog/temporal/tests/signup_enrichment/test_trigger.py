from unittest.mock import patch

from django.test import override_settings

from posthog.temporal.signup_enrichment.trigger import start_signup_enrichment_workflow


def _dispatch_mocks(region="US"):
    """Patch out the transaction/Temporal/DB boundaries so on_commit fires inline."""
    return (
        patch("posthog.temporal.signup_enrichment.trigger.transaction.on_commit", side_effect=lambda fn: fn()),
        patch("posthog.temporal.signup_enrichment.trigger.sync_connect"),
        patch("posthog.temporal.signup_enrichment.trigger.asyncio.run"),
        patch("posthog.temporal.signup_enrichment.trigger.get_instance_region", return_value=region),
        patch("posthog.temporal.signup_enrichment.trigger.record_signup_work_email"),
    )


@override_settings(GROWTH_SIGNUP_ENRICHMENT_ENABLED=True, HARMONIC_API_KEY="key")
def test_dispatches_for_work_email_in_us_and_records_work_email():
    on_commit, connect, run, region, record = _dispatch_mocks()
    with on_commit, connect as connect_mock, run, region, record as record_mock:
        start_signup_enrichment_workflow(organization_id="org-1", distinct_id="d1", email="founder@stripe.com")
    connect_mock.assert_called_once()
    record_mock.assert_called_once_with(organization_id="org-1", work_email=True)


@override_settings(GROWTH_SIGNUP_ENRICHMENT_ENABLED=False, HARMONIC_API_KEY="key")
def test_kill_switch_off_never_dispatches_or_writes():
    on_commit, connect, run, region, record = _dispatch_mocks()
    with on_commit, connect as connect_mock, run, region, record as record_mock:
        start_signup_enrichment_workflow(organization_id="org-1", distinct_id="d1", email="founder@stripe.com")
    connect_mock.assert_not_called()
    record_mock.assert_not_called()


@override_settings(GROWTH_SIGNUP_ENRICHMENT_ENABLED=True, HARMONIC_API_KEY="")
def test_missing_harmonic_key_never_dispatches():
    on_commit, connect, run, region, record = _dispatch_mocks()
    with on_commit, connect as connect_mock, run, region, record:
        start_signup_enrichment_workflow(organization_id="org-1", distinct_id="d1", email="founder@stripe.com")
    connect_mock.assert_not_called()


@override_settings(GROWTH_SIGNUP_ENRICHMENT_ENABLED=True, HARMONIC_API_KEY="key")
def test_non_us_region_never_dispatches():
    on_commit, connect, run, region, record = _dispatch_mocks(region="EU")
    with on_commit, connect as connect_mock, run, region, record:
        start_signup_enrichment_workflow(organization_id="org-1", distinct_id="d1", email="founder@stripe.com")
    connect_mock.assert_not_called()


@override_settings(GROWTH_SIGNUP_ENRICHMENT_ENABLED=True, HARMONIC_API_KEY="key")
def test_personal_email_records_work_email_false_without_provider_dispatch():
    on_commit, connect, run, region, record = _dispatch_mocks()
    with on_commit, connect as connect_mock, run, region, record as record_mock:
        start_signup_enrichment_workflow(organization_id="org-1", distinct_id="d1", email="someone@gmail.com")
    connect_mock.assert_not_called()
    record_mock.assert_called_once_with(organization_id="org-1", work_email=False)


@override_settings(GROWTH_SIGNUP_ENRICHMENT_ENABLED=True, HARMONIC_API_KEY="key")
def test_missing_distinct_id_records_work_email_but_never_dispatches():
    on_commit, connect, run, region, record = _dispatch_mocks()
    with on_commit, connect as connect_mock, run, region, record as record_mock:
        start_signup_enrichment_workflow(organization_id="org-1", distinct_id=None, email="founder@stripe.com")
    connect_mock.assert_not_called()
    record_mock.assert_called_once_with(organization_id="org-1", work_email=True)


@override_settings(GROWTH_SIGNUP_ENRICHMENT_ENABLED=True, HARMONIC_API_KEY="key")
def test_work_email_write_failure_does_not_block_dispatch():
    on_commit, connect, run, region, record = _dispatch_mocks()
    with on_commit, connect as connect_mock, run, region, record as record_mock:
        record_mock.side_effect = RuntimeError("db down")
        with patch("posthog.temporal.signup_enrichment.trigger.capture_exception") as capture_mock:
            start_signup_enrichment_workflow(organization_id="org-1", distinct_id="d1", email="founder@stripe.com")
    connect_mock.assert_called_once()
    capture_mock.assert_called_once()
