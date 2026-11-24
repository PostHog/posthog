from unittest.mock import Mock, patch

from posthog.dags.common.favicons import DownloadedFavicon


def _run_account_asset(account_domains, cached=frozenset(), failed=None, time_budget=None):
    import dagster

    from products.customer_analytics.dags.cache_account_favicons import (
        CacheFaviconsConfig,
        cache_account_domain_favicons,
    )

    context = dagster.build_asset_context()
    s3 = Mock()
    s3.get_client.return_value = Mock()
    module = "products.customer_analytics.dags.cache_account_favicons"
    favicons_module = "posthog.dags.common.favicons"
    with (
        patch(f"{favicons_module}.httpx.Client"),
        patch(f"{module}.list_logo_domains_across_teams", return_value=account_domains) as mock_list_domains,
        patch(f"{module}.get_last_cached_domains", return_value=set(cached)),
        patch(f"{module}.get_recently_failed_domains", return_value=failed or {}),
        patch(f"{favicons_module}.download_favicon") as mock_download,
        patch(f"{favicons_module}.upload_if_missing") as mock_upload,
        patch(f"{favicons_module}.settings") as mock_settings,
    ):
        if time_budget is not None:
            patch(f"{module}.ACCOUNT_FAVICONS_RUN_TIME_BUDGET", time_budget).start()
        mock_settings.DAGSTER_FAVICONS_S3_BUCKET = "test-bucket"
        mock_download.side_effect = lambda _context, domain, _client: (
            None
            if domain.startswith("missing")
            else DownloadedFavicon(data=b"data", content_type="image/png", source_url="http://url")
        )
        try:
            result: dagster.MaterializeResult = cache_account_domain_favicons(context, s3, CacheFaviconsConfig())  # type: ignore[assignment]  # ty: ignore[invalid-assignment]
        finally:
            patch.stopall()
    assert result.metadata is not None
    return result.metadata, mock_list_domains, mock_download, mock_upload


class TestCacheAccountDomainFaviconsAsset:
    def test_caches_new_account_domains_under_the_shared_favicon_key(self):
        metadata, mock_list_domains, mock_download, mock_upload = _run_account_asset(
            ["acme.example", "cached.example"], cached={"cached.example"}
        )

        mock_list_domains.assert_called_once_with(limit=500_000, per_team_limit=50_000)
        mock_download.assert_called_once()
        assert mock_upload.call_args.args[3] == "favicons/acme.example"
        assert metadata["account_domains_queried"] == 2
        assert metadata["domains_skipped"] == 1
        assert metadata["favicons_cached"] == 1

    def test_holds_back_recent_failures_and_records_new_ones(self):
        metadata, _, mock_download, _ = _run_account_asset(
            ["acme.example", "missing.example", "failed-before.example"],
            failed={"failed-before.example": "2026-01-01"},
        )

        assert [call.args[1] for call in mock_download.call_args_list] == ["acme.example", "missing.example"]
        assert metadata["domains_failed"] == 1
        assert metadata["domains_held_back"] == 1
        assert set(metadata["failed_domains"]) == {"missing.example", "failed-before.example"}
        assert "missing.example" not in metadata["cached_domains"]

    def test_stops_downloading_when_the_time_budget_is_spent(self):
        import datetime as dt

        metadata, _, mock_download, _ = _run_account_asset(
            ["acme.example", "globex.example"], time_budget=dt.timedelta(0)
        )

        mock_download.assert_not_called()
        assert metadata["out_of_time"] is True
        assert metadata["favicons_cached"] == 0


class TestGetRecentlyFailedDomains:
    def test_keeps_only_failures_inside_the_retry_window(self):
        import datetime as dt

        import dagster

        from products.customer_analytics.dags.cache_account_favicons import get_recently_failed_domains

        context = Mock()
        context.instance.get_latest_materialization_event.return_value.asset_materialization.metadata = {
            "failed_domains": dagster.JsonMetadataValue({"recent.example": "2026-11-20", "old.example": "2026-11-01"})
        }

        failed = get_recently_failed_domains(context, "cache_account_domain_favicons", dt.datetime(2026, 11, 24))

        assert failed == {"recent.example": "2026-11-20"}


class TestCacheAccountDomainFaviconsSchedule:
    def test_skips_while_a_run_is_still_executing(self):
        import dagster

        from products.customer_analytics.dags.cache_account_favicons import (
            cache_account_domain_favicons_job,
            cache_account_domain_favicons_schedule,
        )

        with dagster.instance_for_test() as instance:
            context = dagster.build_schedule_context(instance=instance)
            assert isinstance(cache_account_domain_favicons_schedule(context), dagster.RunRequest)

            instance.add_run(
                dagster.DagsterRun(
                    job_name=cache_account_domain_favicons_job.name, status=dagster.DagsterRunStatus.STARTED
                )
            )

            assert isinstance(cache_account_domain_favicons_schedule(context), dagster.SkipReason)
