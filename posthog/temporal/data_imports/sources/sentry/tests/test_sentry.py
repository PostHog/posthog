from datetime import UTC, datetime
from typing import Any, cast

import pytest
from unittest.mock import Mock, patch

from parameterized import parameterized

from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.generated_configs import SentrySourceConfig
from posthog.temporal.data_imports.sources.sentry.sentry import (
    SentryPaginator,
    SentryResumeConfig,
    _normalize_api_base_url,
    _parse_next_link,
    _retry_wait_seconds,
    _start_param_for_sentry,
    get_resource,
    sentry_source,
    validate_credentials,
)
from posthog.temporal.data_imports.sources.sentry.source import SentrySource


def _response(payload, status_code: int = 200, link_header: str = "") -> Mock:
    response = Mock()
    response.status_code = status_code
    response.headers = {"Link": link_header}
    response.json.return_value = payload
    response.text = "error"

    def _raise_for_status() -> None:
        if status_code >= 400:
            raise Exception(f"{status_code} client error")

    response.raise_for_status = _raise_for_status
    return response


def _make_fake_manager(
    can_resume: bool = False, state: SentryResumeConfig | None = None
) -> ResumableSourceManager[SentryResumeConfig]:
    manager = Mock(spec=ResumableSourceManager)
    manager.can_resume.return_value = can_resume
    manager.load_state.return_value = state
    return cast(ResumableSourceManager[SentryResumeConfig], manager)


class _FakeDltResource:
    """Lightweight stand-in for a DltResource returned by rest_api_resources.

    ``process_parent_data_item`` injects parent fields as
    ``_<parent_resource>_<field>`` (see ``make_parent_key_name``), so test
    data should include those prefixed keys to exercise the row mappers.
    """

    def __init__(self, name: str, rows: list[dict]) -> None:
        self.name = name
        self._rows = rows

    def add_map(self, mapper):
        self._rows = [mapper(dict(row)) for row in self._rows]
        return self

    def __iter__(self):
        return iter(self._rows)


class TestSentryTransport:
    def test_normalize_api_base_url(self) -> None:
        assert _normalize_api_base_url(None) == "https://sentry.io"
        assert _normalize_api_base_url("https://us.sentry.io/") == "https://us.sentry.io"

    def test_start_param_for_sentry_formats_datetime(self) -> None:
        value = datetime(2025, 1, 1, 10, 30, 0, tzinfo=UTC)
        assert _start_param_for_sentry(value) == "2025-01-01T10:30:00"

    def test_start_param_for_sentry_caps_future_datetime(self) -> None:
        value = datetime(2999, 1, 1, 0, 0, 0, tzinfo=UTC)
        assert _start_param_for_sentry(value) != "2999-01-01T00:00:00"

    @parameterized.expand(
        [
            (
                "has_next",
                '<https://sentry.io/api/0/organizations/acme/issues/?cursor=0:100:0>; rel="next"; results="true"',
                True,
            ),
            (
                "no_more_results",
                '<https://sentry.io/api/0/organizations/acme/issues/?cursor=0:100:0>; rel="next"; results="false"',
                False,
            ),
            ("missing_link", "", False),
        ]
    )
    def test_paginator_update_state(self, _name, link_header, expected_has_next) -> None:
        paginator = SentryPaginator()
        response = Mock()
        response.headers = {"Link": link_header}

        paginator.update_state(response)

        assert paginator.has_next_page == expected_has_next

    def test_paginator_update_request_sets_next_url(self) -> None:
        paginator = SentryPaginator()
        response = Mock()
        response.headers = {
            "Link": '<https://sentry.io/api/0/organizations/acme/issues/?cursor=0:100:0>; rel="next"; results="true"'
        }
        paginator.update_state(response)

        request = Mock()
        request.url = "/api/0/organizations/acme/issues/"
        request.params = {"limit": 100}
        paginator.update_request(request)

        assert request.url == "https://sentry.io/api/0/organizations/acme/issues/?cursor=0:100:0"
        assert request.params == {}

    def test_paginator_get_resume_state_returns_next_url_when_has_next(self) -> None:
        paginator = SentryPaginator()
        response = Mock()
        response.headers = {
            "Link": '<https://sentry.io/api/0/organizations/acme/issues/?cursor=0:100:0>; rel="next"; results="true"'
        }
        paginator.update_state(response)

        assert paginator.get_resume_state() == {
            "next_url": "https://sentry.io/api/0/organizations/acme/issues/?cursor=0:100:0"
        }

    def test_paginator_get_resume_state_returns_none_when_exhausted(self) -> None:
        paginator = SentryPaginator()
        response = Mock()
        response.headers = {"Link": ""}
        paginator.update_state(response)

        assert paginator.get_resume_state() is None

    def test_paginator_set_resume_state_seeds_initial_request(self) -> None:
        paginator = SentryPaginator()
        paginator.set_resume_state({"next_url": "https://sentry.io/api/0/organizations/acme/issues/?cursor=0:100:2"})

        assert paginator.has_next_page is True

        request = Mock()
        request.url = "https://sentry.io/api/0/organizations/acme/issues/"
        request.params = {"limit": 100}
        paginator.init_request(request)

        assert request.url == "https://sentry.io/api/0/organizations/acme/issues/?cursor=0:100:2"
        assert request.params == {}

    def test_get_resource_incremental_issues(self) -> None:
        resource = cast(
            dict[str, Any],
            get_resource(
                endpoint="issues",
                organization_slug="acme",
                should_use_incremental_field=True,
                incremental_field="lastSeen",
            ),
        )

        assert resource["name"] == "issues"
        assert resource["write_disposition"]["disposition"] == "merge"
        assert resource["endpoint"]["params"]["query"] == ""
        assert resource["endpoint"]["params"]["sort"] == "date"
        assert "start" not in resource["endpoint"]["params"]
        assert resource["endpoint"]["incremental"]["start_param"] == "start"
        assert resource["endpoint"]["incremental"]["end_param"] == "end"
        assert resource["endpoint"]["incremental"]["cursor_path"] == "lastSeen"

    @parameterized.expand(
        [
            ("projects", "/organizations/acme/projects/"),
            ("teams", "/organizations/acme/teams/"),
            ("members", "/organizations/acme/members/"),
            ("releases", "/organizations/acme/releases/"),
            ("environments", "/organizations/acme/environments/"),
            ("monitors", "/organizations/acme/monitors/"),
        ]
    )
    def test_get_resource_non_fanout_shape(self, endpoint, expected_path) -> None:
        resource = cast(
            dict[str, Any],
            get_resource(
                endpoint=endpoint,
                organization_slug="acme",
                should_use_incremental_field=False,
            ),
        )

        assert resource["name"] == endpoint
        assert resource["write_disposition"] == "replace"
        assert resource["endpoint"]["path"] == expected_path
        assert resource["table_format"] == "delta"

    @parameterized.expand(
        [
            ("project_events",),
            ("project_users",),
            ("project_client_keys",),
            ("project_service_hooks",),
            ("issue_events",),
            ("issue_hashes",),
            ("issue_tag_values",),
        ]
    )
    def test_get_resource_rejects_fanout_endpoints(self, endpoint) -> None:
        with pytest.raises(ValueError, match="Fan-out endpoint"):
            get_resource(
                endpoint=endpoint,
                organization_slug="acme",
                should_use_incremental_field=False,
            )

    def test_validate_credentials_rejects_unknown_api_base_url(self) -> None:
        result = validate_credentials(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://example.sentry.invalid",
        )

        assert result == (
            False,
            "API base URL must be one of https://sentry.io, https://us.sentry.io, or https://de.sentry.io.",
        )

    def test_sentry_source_rejects_unknown_api_base_url_at_runtime(self) -> None:
        with pytest.raises(
            ValueError,
            match="API base URL must be one of https://sentry.io, https://us.sentry.io, or https://de.sentry.io.",
        ):
            sentry_source(
                auth_token="token",
                organization_slug="acme",
                api_base_url="https://example.sentry.invalid",
                endpoint="issues",
                team_id=123,
                job_id="job-id",
            )


class TestSentrySourceValidation:
    @patch("posthog.temporal.data_imports.sources.sentry.source.validate_sentry_credentials")
    def test_validate_credentials_rejects_unknown_api_base_url(self, mock_validate) -> None:
        source = SentrySource()
        config = SentrySourceConfig(
            auth_token="token",
            organization_slug="acme",
            api_base_url=cast(Any, "https://example.sentry.invalid"),
        )

        result = source.validate_credentials(config, team_id=1)

        assert result == (
            False,
            "API base URL must be one of https://sentry.io, https://us.sentry.io, or https://de.sentry.io.",
        )
        mock_validate.assert_not_called()

    @patch("posthog.temporal.data_imports.sources.sentry.source.validate_sentry_credentials")
    def test_validate_credentials_defaults_missing_api_base_url(self, mock_validate) -> None:
        source = SentrySource()
        config = SentrySourceConfig(
            auth_token="token",
            organization_slug="acme",
        )
        mock_validate.return_value = (True, None)

        result = source.validate_credentials(config, team_id=1)

        assert result == (True, None)
        mock_validate.assert_called_once_with(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
        )

    @patch("posthog.temporal.data_imports.sources.sentry.sentry.rest_api_resource")
    def test_sentry_source_builds_response(self, mock_rest_api_resource) -> None:
        mock_resource = Mock()
        mock_rest_api_resource.return_value = mock_resource

        resp = sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint="issues",
            team_id=123,
            job_id="job-id",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2025, 1, 1, 10, 30, 0),
            incremental_field="lastSeen",
        )

        assert resp.name == "issues"
        assert resp.primary_keys == ["id"]
        assert resp.partition_mode == "datetime"

    # ----- Project fan-out (dependent resources) -----

    @parameterized.expand(
        [
            ("project_events", {"eventID": "evt-1", "_projects_id": "1", "_projects_slug": "web"}),
            ("project_users", {"id": "usr-1", "_projects_id": "1", "_projects_slug": "web"}),
            ("project_client_keys", {"id": "key-1", "_projects_id": "1", "_projects_slug": "web"}),
            ("project_service_hooks", {"id": "hook-1", "_projects_id": "1", "_projects_slug": "web"}),
        ]
    )
    @patch("posthog.temporal.data_imports.sources.common.rest_source.fanout.rest_api_resources")
    def test_project_fanout_row_format(self, endpoint, child_row, mock_rest_api_resources) -> None:
        mock_rest_api_resources.return_value = [
            _FakeDltResource("projects", [{"id": "1", "slug": "web"}]),
            _FakeDltResource(endpoint, [child_row]),
        ]

        resp = sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint=endpoint,
            team_id=123,
            job_id="job-id",
        )

        rows = list(cast(Any, resp.items()))
        assert len(rows) == 1
        row = rows[0]
        assert row["project_id"] == "1"
        assert row["project_slug"] == "web"
        assert "_projects_id" not in row
        assert "_projects_slug" not in row

    # ----- Issue fan-out: dependent resources (issue_events, issue_hashes) -----

    @parameterized.expand(
        [
            ("issue_events", {"eventID": "evt-1", "_issues_id": "100"}),
            ("issue_hashes", {"id": "hash-1", "hash": "abc", "_issues_id": "100"}),
        ]
    )
    @patch("posthog.temporal.data_imports.sources.common.rest_source.fanout.rest_api_resources")
    def test_issue_fanout_dependent_resource_row_format(self, endpoint, child_row, mock_rest_api_resources) -> None:
        mock_rest_api_resources.return_value = [
            _FakeDltResource("issues", [{"id": "100"}]),
            _FakeDltResource(endpoint, [child_row]),
        ]

        resp = sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint=endpoint,
            team_id=123,
            job_id="job-id",
        )

        rows = list(cast(Any, resp.items()))
        assert len(rows) == 1
        row = rows[0]
        assert row["issue_id"] == "100"
        assert "_issues_id" not in row

    # ----- Issue fan-out: custom iterator (issue_tag_values) -----

    @patch("posthog.temporal.data_imports.sources.sentry.sentry.requests.get")
    def test_issue_tag_values_custom_fanout_row_format(self, mock_get) -> None:
        seen_issues_params: list[dict | None] = []
        seen_values_params: list[dict | None] = []

        def side_effect(url, headers=None, params=None, timeout=None):
            if url.endswith("/organizations/acme/issues/"):
                seen_issues_params.append(params)
                return _response([{"id": "100"}])
            if url.endswith("/organizations/acme/issues/100/tags/"):
                return _response([{"key": "browser"}])
            if url.endswith("/organizations/acme/issues/100/tags/browser/values/"):
                seen_values_params.append(params)
                return _response([{"value": "Chrome", "timesSeen": 1}])
            return _response([])

        mock_get.side_effect = side_effect

        resp = sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint="issue_tag_values",
            team_id=123,
            job_id="job-id",
        )

        rows = list(cast(Any, resp.items()))
        assert len(rows) == 1
        row = rows[0]
        assert row["issue_id"] == "100"
        assert row["tag_key"] == "browser"
        assert seen_issues_params == [{"limit": 100, "query": "", "sort": "date"}]
        assert seen_values_params == [{"limit": 100, "sort": "-date"}]

    @patch("posthog.temporal.data_imports.sources.sentry.sentry.requests.get")
    def test_issue_tag_values_incremental_stops_at_last_seen_cutoff(self, mock_get) -> None:
        cutoff = datetime(2026, 3, 3, 0, 0, 0, tzinfo=UTC)

        def side_effect(url, headers=None, params=None, timeout=None):
            if url.endswith("/organizations/acme/issues/"):
                return _response([{"id": "100"}])
            if url.endswith("/organizations/acme/issues/100/tags/"):
                return _response([{"key": "browser"}])
            if url.endswith("/organizations/acme/issues/100/tags/browser/values/"):
                return _response(
                    [
                        {"value": "Chrome", "lastSeen": "2026-03-05T12:00:00Z"},
                        {"value": "Firefox", "lastSeen": "2026-03-01T09:00:00Z"},
                    ],
                    link_header='<https://sentry.io/api/0/organizations/acme/issues/100/tags/browser/values/?cursor=0:100:0>; rel="next"; results="true"',
                )
            if "tags/browser/values/?cursor=0:100:0" in url:
                raise AssertionError("should not request the next page after reaching cutoff")
            return _response([])

        mock_get.side_effect = side_effect

        resp = sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint="issue_tag_values",
            team_id=123,
            job_id="job-id",
            should_use_incremental_field=True,
            db_incremental_field_last_value=cutoff,
            incremental_field="lastSeen",
        )

        rows = list(cast(Any, resp.items()))
        assert rows == [
            {"value": "Chrome", "lastSeen": "2026-03-05T12:00:00Z", "issue_id": "100", "tag_key": "browser"}
        ]


class TestSentrySourceResumable:
    """Resume behaviour for flat endpoints (rest_api_resource path)."""

    @patch("posthog.temporal.data_imports.sources.sentry.sentry.rest_api_resource")
    def test_fresh_run_passes_resume_hook_and_no_initial_state(self, mock_rest_api_resource) -> None:
        mock_rest_api_resource.return_value = Mock()
        manager = _make_fake_manager(can_resume=False)

        sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint="projects",
            team_id=123,
            job_id="job-id",
            resumable_source_manager=manager,
        )

        _, kwargs = mock_rest_api_resource.call_args
        assert kwargs["initial_paginator_state"] is None
        assert callable(kwargs["resume_hook"])

        # save_checkpoint should forward the next page into manager.save_state
        kwargs["resume_hook"]({"next_url": "https://sentry.io/api/0/organizations/acme/projects/?cursor=0:100:0"})
        cast(Mock, manager.save_state).assert_called_once_with(
            SentryResumeConfig(next_url="https://sentry.io/api/0/organizations/acme/projects/?cursor=0:100:0")
        )

    @patch("posthog.temporal.data_imports.sources.sentry.sentry.rest_api_resource")
    def test_resume_run_seeds_initial_paginator_state_from_loaded_config(self, mock_rest_api_resource) -> None:
        mock_rest_api_resource.return_value = Mock()
        resume_url = "https://sentry.io/api/0/organizations/acme/projects/?cursor=0:100:2"
        manager = _make_fake_manager(can_resume=True, state=SentryResumeConfig(next_url=resume_url))

        sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint="projects",
            team_id=123,
            job_id="job-id",
            resumable_source_manager=manager,
        )

        _, kwargs = mock_rest_api_resource.call_args
        assert kwargs["initial_paginator_state"] == {"next_url": resume_url}

    @patch("posthog.temporal.data_imports.sources.sentry.sentry.rest_api_resource")
    def test_resume_hook_noop_when_no_next_page(self, mock_rest_api_resource) -> None:
        mock_rest_api_resource.return_value = Mock()
        manager = _make_fake_manager(can_resume=False)

        sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint="projects",
            team_id=123,
            job_id="job-id",
            resumable_source_manager=manager,
        )

        _, kwargs = mock_rest_api_resource.call_args
        kwargs["resume_hook"](None)
        kwargs["resume_hook"]({})
        cast(Mock, manager.save_state).assert_not_called()

    @patch("posthog.temporal.data_imports.sources.sentry.sentry.rest_api_resource")
    def test_no_manager_disables_resume(self, mock_rest_api_resource) -> None:
        mock_rest_api_resource.return_value = Mock()

        sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint="projects",
            team_id=123,
            job_id="job-id",
        )

        _, kwargs = mock_rest_api_resource.call_args
        assert kwargs["initial_paginator_state"] is None
        assert kwargs["resume_hook"] is None


class TestIssueTagValuesResumable:
    """Resume behaviour for the two-level issue_tag_values fan-out loop."""

    @patch("posthog.temporal.data_imports.sources.sentry.sentry.requests.get")
    def test_fresh_run_saves_state_pointing_to_next_values_page(self, mock_get) -> None:
        next_values_link = (
            "<https://sentry.io/api/0/organizations/acme/issues/100/tags/browser/values/?cursor=0:100:2>; "
            'rel="next"; results="true"'
        )

        def side_effect(url, headers=None, params=None, timeout=None):
            if url.endswith("/organizations/acme/issues/"):
                return _response([{"id": "100"}])
            if url.endswith("/organizations/acme/issues/100/tags/"):
                return _response([{"key": "browser"}])
            if url.endswith("/organizations/acme/issues/100/tags/browser/values/"):
                return _response([{"value": "Chrome"}], link_header=next_values_link)
            # Second values page returns empty + no link header to end the loop
            return _response([])

        mock_get.side_effect = side_effect
        manager = _make_fake_manager(can_resume=False)

        resp = sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint="issue_tag_values",
            team_id=123,
            job_id="job-id",
            resumable_source_manager=manager,
        )

        rows = list(cast(Any, resp.items()))
        assert len(rows) == 1
        assert rows[0]["issue_id"] == "100"
        assert rows[0]["tag_key"] == "browser"

        saved_calls = cast(Mock, manager.save_state).call_args_list
        assert len(saved_calls) == 1
        saved_state = saved_calls[0].args[0]
        assert saved_state == SentryResumeConfig(
            issue_id="100",
            tag_key="browser",
            values_next_url="https://sentry.io/api/0/organizations/acme/issues/100/tags/browser/values/?cursor=0:100:2",
        )

    @patch("posthog.temporal.data_imports.sources.sentry.sentry.requests.get")
    def test_resume_fetches_saved_values_url_and_skips_earlier_pairs(self, mock_get) -> None:
        seen_urls: list[str] = []
        resume_url = "https://sentry.io/api/0/organizations/acme/issues/100/tags/browser/values/?cursor=0:100:2"

        def side_effect(url, headers=None, params=None, timeout=None):
            seen_urls.append(url)
            if url.endswith("/organizations/acme/issues/"):
                return _response([{"id": "99"}, {"id": "100"}, {"id": "101"}])
            if url.endswith("/organizations/acme/issues/100/tags/"):
                return _response([{"key": "os"}, {"key": "browser"}])
            if url == resume_url:
                return _response([{"value": "Firefox"}])
            # Any other URL shouldn't be hit on resume; fall back to empty
            return _response([])

        mock_get.side_effect = side_effect
        manager = _make_fake_manager(
            can_resume=True,
            state=SentryResumeConfig(issue_id="100", tag_key="browser", values_next_url=resume_url),
        )

        resp = sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint="issue_tag_values",
            team_id=123,
            job_id="job-id",
            resumable_source_manager=manager,
        )

        rows = list(cast(Any, resp.items()))
        assert rows == [{"value": "Firefox", "issue_id": "100", "tag_key": "browser"}]

        # We should have fetched the resume values URL directly, and NOT
        # issued the initial page for that (issue, tag) pair.
        assert resume_url in seen_urls
        initial_values_url = "https://sentry.io/api/0/organizations/acme/issues/100/tags/browser/values/"
        assert initial_values_url not in seen_urls

    @patch("posthog.temporal.data_imports.sources.sentry.sentry._RESUME_ISSUE_SKIP_LIMIT", 2)
    @patch("posthog.temporal.data_imports.sources.sentry.sentry.requests.get")
    def test_stale_checkpoint_falls_through_after_skip_limit(self, mock_get) -> None:
        """If the checkpoint issue was deleted between runs, bounded skipping
        falls through so subsequent issues still get processed."""

        def side_effect(url, headers=None, params=None, timeout=None):
            if url.endswith("/organizations/acme/issues/"):
                # None of these match the checkpoint issue_id=999.
                return _response([{"id": "100"}, {"id": "101"}, {"id": "102"}])
            if url.endswith("/organizations/acme/issues/102/tags/"):
                return _response([{"key": "browser"}])
            if url.endswith("/organizations/acme/issues/102/tags/browser/values/"):
                return _response([{"value": "Chrome"}])
            return _response([])

        mock_get.side_effect = side_effect
        manager = _make_fake_manager(
            can_resume=True,
            state=SentryResumeConfig(
                issue_id="999",
                tag_key="browser",
                values_next_url="https://sentry.io/api/0/organizations/acme/issues/999/tags/browser/values/?cursor=0:100:2",
            ),
        )

        resp = sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint="issue_tag_values",
            team_id=123,
            job_id="job-id",
            resumable_source_manager=manager,
        )

        rows = list(cast(Any, resp.items()))
        # With skip limit 2, issues 100 and 101 are skipped; on 102 we exceed
        # the limit, clear the markers, and process it fresh.
        assert rows == [{"value": "Chrome", "issue_id": "102", "tag_key": "browser"}]

    @patch("posthog.temporal.data_imports.sources.sentry.sentry.requests.get")
    def test_partial_resume_state_falls_through_to_fresh_run(self, mock_get) -> None:
        """Only activate resume when the full (issue_id, tag_key, values_next_url)
        triple is present; partial state must fall through to a fresh run."""

        def side_effect(url, headers=None, params=None, timeout=None):
            if url.endswith("/organizations/acme/issues/"):
                return _response([{"id": "100"}])
            if url.endswith("/organizations/acme/issues/100/tags/"):
                return _response([{"key": "browser"}])
            if url.endswith("/organizations/acme/issues/100/tags/browser/values/"):
                return _response([{"value": "Chrome"}])
            return _response([])

        mock_get.side_effect = side_effect
        # issue_id set, but tag_key + values_next_url are missing → partial state.
        manager = _make_fake_manager(
            can_resume=True,
            state=SentryResumeConfig(issue_id="100"),
        )

        resp = sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint="issue_tag_values",
            team_id=123,
            job_id="job-id",
            resumable_source_manager=manager,
        )

        rows = list(cast(Any, resp.items()))
        assert rows == [{"value": "Chrome", "issue_id": "100", "tag_key": "browser"}]

    @patch("posthog.temporal.data_imports.sources.sentry.sentry.requests.get")
    def test_resume_with_empty_state_falls_through_to_fresh_run(self, mock_get) -> None:
        def side_effect(url, headers=None, params=None, timeout=None):
            if url.endswith("/organizations/acme/issues/"):
                return _response([{"id": "100"}])
            if url.endswith("/organizations/acme/issues/100/tags/"):
                return _response([{"key": "browser"}])
            if url.endswith("/organizations/acme/issues/100/tags/browser/values/"):
                return _response([{"value": "Chrome"}])
            return _response([])

        mock_get.side_effect = side_effect
        # can_resume=True but state.issue_id is None — should fall through.
        manager = _make_fake_manager(can_resume=True, state=SentryResumeConfig())

        resp = sentry_source(
            auth_token="token",
            organization_slug="acme",
            api_base_url="https://sentry.io",
            endpoint="issue_tag_values",
            team_id=123,
            job_id="job-id",
            resumable_source_manager=manager,
        )

        rows = list(cast(Any, resp.items()))
        assert rows == [{"value": "Chrome", "issue_id": "100", "tag_key": "browser"}]


class TestSentrySourceIntegration:
    """End-to-end wiring of the ResumableSource class."""

    def test_source_returns_resumable_manager(self) -> None:
        source = SentrySource()
        inputs = Mock()
        inputs.team_id = 7
        inputs.job_id = "job-x"
        inputs.logger = Mock()

        manager = source.get_resumable_source_manager(inputs)

        assert isinstance(manager, ResumableSourceManager)


class TestHelpers:
    @parameterized.expand(
        [
            ("has_next", '<https://a.io/next>; rel="next"; results="true"', "https://a.io/next"),
            ("no_results", '<https://a.io/next>; rel="next"; results="false"', None),
            ("empty", "", None),
            ("only_prev", '<https://a.io/prev>; rel="previous"; results="true"', None),
        ]
    )
    def test_parse_next_link(self, _name, link_header, expected) -> None:
        assert _parse_next_link(link_header) == expected

    def test_retry_wait_uses_exponential_fallback_for_non_429(self) -> None:
        state = Mock()
        state.attempt_number = 3
        state.outcome = Mock()
        state.outcome.failed = False
        state.outcome.result.return_value = Mock(status_code=500)

        assert _retry_wait_seconds(state) == 4.0

    @patch("posthog.temporal.data_imports.sources.sentry.sentry.datetime")
    def test_retry_wait_uses_rate_limit_reset_header_for_429(self, mock_datetime) -> None:
        now = datetime(2026, 3, 6, 12, 0, 0, tzinfo=UTC)
        mock_datetime.now.return_value = now

        state = Mock()
        state.attempt_number = 2
        state.outcome = Mock()
        state.outcome.failed = False
        state.outcome.result.return_value = Mock(
            status_code=429,
            headers={"X-Sentry-Rate-Limit-Reset": str(int(now.timestamp()) + 9)},
        )

        assert _retry_wait_seconds(state) == 9.0
