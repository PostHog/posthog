from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.models.group_type_mapping import (
    GROUP_TYPES_CACHE_KEY_PREFIX,
    GROUP_TYPES_CONFIRMED_EMPTY_CACHE_KEY_PREFIX,
    GROUP_TYPES_STALE_CACHE_KEY_PREFIX,
    GroupTypeMapping,
    GroupTypesUnavailable,
    _dict_to_group_type_mapping_model,
    _fetch_group_types_for_projects_via_personhog,
    _record_group_types_fetch_failure,
    clear_dashboard_from_group_type_mapping,
    count_group_type_mappings_per_team,
    delete_group_type_mapping,
    get_group_type_mapping_instance,
    get_group_types_for_project,
    get_group_types_for_projects,
    get_group_types_for_team,
    invalidate_group_types_cache,
    project_has_group_types_authoritatively,
    update_group_type_mapping_fields,
)
from posthog.utils import get_safe_cache, safe_cache_delete, safe_cache_set


def _clear_cache(project_id: int) -> None:
    safe_cache_delete(f"{GROUP_TYPES_CACHE_KEY_PREFIX}{project_id}")
    safe_cache_delete(f"{GROUP_TYPES_STALE_CACHE_KEY_PREFIX}{project_id}")


PERSONHOG_SUCCESS_DATA = [
    {
        "group_type": "organization",
        "group_type_index": 0,
        "name_singular": "Organization",
        "name_plural": "Organizations",
        "detail_dashboard": None,
        "default_columns": ["name"],
        "created_at": None,
    },
    {
        "group_type": "company",
        "group_type_index": 1,
        "name_singular": None,
        "name_plural": None,
        "detail_dashboard": None,
        "default_columns": None,
        "created_at": None,
    },
]

_CLIENT_PATCH = "posthog.personhog_client.client.get_personhog_client"


class TestGetGroupTypesForProject(SimpleTestCase):
    def setUp(self):
        self.project_id = 999
        _clear_cache(self.project_id)
        self._client_patcher = patch(_CLIENT_PATCH, return_value=MagicMock())
        self._client_patcher.start()

    def tearDown(self):
        self._client_patcher.stop()
        _clear_cache(self.project_id)

    @patch("posthog.models.group_type_mapping.GroupTypeMapping.objects")
    @patch("posthog.models.group_type_mapping._fetch_group_types_via_personhog")
    def test_personhog_success_returns_data_and_caches(
        self,
        mock_fetch_personhog,
        mock_objects,
    ):
        mock_fetch_personhog.return_value = PERSONHOG_SUCCESS_DATA

        result = get_group_types_for_project(self.project_id)

        assert len(result) == 2
        mock_objects.filter.assert_not_called()

    @patch("posthog.models.group_type_mapping._fetch_group_types_via_personhog")
    def test_personhog_failure_without_stale_returns_empty(
        self,
        mock_fetch_personhog,
    ):
        mock_fetch_personhog.side_effect = RuntimeError("grpc timeout")

        result = get_group_types_for_project(self.project_id)

        assert result == []

    @patch("posthog.models.group_type_mapping.GroupTypeMapping.objects")
    def test_cache_hit_skips_both_paths(self, mock_objects):
        from posthog.utils import safe_cache_set

        cached_data = [{"group_type": "cached", "group_type_index": 0}]
        safe_cache_set(f"{GROUP_TYPES_CACHE_KEY_PREFIX}{self.project_id}", cached_data, 60)

        result = get_group_types_for_project(self.project_id)

        assert result == cached_data
        mock_objects.filter.assert_not_called()

    @patch("posthog.models.group_type_mapping._fetch_group_types_via_personhog")
    def test_personhog_failure_returns_stale_cache(
        self,
        mock_fetch_personhog,
    ):
        from posthog.utils import safe_cache_set

        stale_data = [{"group_type": "stale", "group_type_index": 0}]
        safe_cache_set(f"{GROUP_TYPES_STALE_CACHE_KEY_PREFIX}{self.project_id}", stale_data, 3600)

        mock_fetch_personhog.side_effect = RuntimeError("grpc timeout")

        result = get_group_types_for_project(self.project_id)

        assert result == stale_data


class TestGetGroupTypesForTeam(SimpleTestCase):
    def setUp(self):
        self.team_id = 42
        self._client_patcher = patch(_CLIENT_PATCH, return_value=MagicMock())
        self._client_patcher.start()

    def tearDown(self):
        self._client_patcher.stop()

    @patch("posthog.models.group_type_mapping.GroupTypeMapping.objects")
    @patch("posthog.models.group_type_mapping._fetch_group_types_for_team_via_personhog")
    def test_personhog_success_returns_data_without_orm(
        self,
        mock_fetch_personhog,
        mock_objects,
    ):
        mock_fetch_personhog.return_value = PERSONHOG_SUCCESS_DATA

        result = get_group_types_for_team(self.team_id)

        assert result == PERSONHOG_SUCCESS_DATA
        mock_objects.filter.assert_not_called()

    @patch("posthog.models.group_type_mapping._fetch_group_types_for_team_via_personhog")
    def test_personhog_failure_returns_empty(
        self,
        mock_fetch_personhog,
    ):
        mock_fetch_personhog.side_effect = RuntimeError("grpc timeout")

        result = get_group_types_for_team(self.team_id)

        assert result == []


class TestGetGroupTypesForProjects(SimpleTestCase):
    def setUp(self):
        self.project_ids = [1, 2, 3]
        self._client_patcher = patch(_CLIENT_PATCH, return_value=MagicMock())
        self._client_patcher.start()

    def tearDown(self):
        self._client_patcher.stop()

    @override_settings(PERSONHOG_BATCH_SIZE=2)
    def test_fetch_via_personhog_chunks_project_ids(self):
        # 5 project_ids with batch size 2 → 3 chunks (2 + 2 + 1)
        mock_client = MagicMock()
        mock_client.get_group_type_mappings_by_project_ids.side_effect = [
            MagicMock(results=[MagicMock(key=1, mappings=[]), MagicMock(key=2, mappings=[])]),
            MagicMock(results=[MagicMock(key=3, mappings=[]), MagicMock(key=4, mappings=[])]),
            MagicMock(results=[MagicMock(key=5, mappings=[])]),
        ]

        result = _fetch_group_types_for_projects_via_personhog(mock_client, [1, 2, 3, 4, 5])

        assert mock_client.get_group_type_mappings_by_project_ids.call_count == 3
        assert set(result.keys()) == {1, 2, 3, 4, 5}
        for c in mock_client.get_group_type_mappings_by_project_ids.call_args_list:
            assert len(c[0][0].project_ids) <= 2

    @patch("posthog.models.group_type_mapping.GroupTypeMapping.objects")
    @patch("posthog.models.group_type_mapping._fetch_group_types_for_projects_via_personhog")
    def test_personhog_success_returns_grouped_data_without_orm(
        self,
        mock_fetch_personhog,
        mock_objects,
    ):
        personhog_result = {
            1: [{"group_type": "organization", "group_type_index": 0}],
            2: [{"group_type": "company", "group_type_index": 0}],
            3: [],
        }
        mock_fetch_personhog.return_value = personhog_result

        result = get_group_types_for_projects(self.project_ids)

        assert result == personhog_result
        mock_objects.filter.assert_not_called()

    @patch("posthog.models.group_type_mapping._fetch_group_types_for_projects_via_personhog")
    def test_personhog_failure_without_stale_raises_unavailable(
        self,
        mock_fetch_personhog,
    ):
        for pid in self.project_ids:
            _clear_cache(pid)
        mock_fetch_personhog.side_effect = RuntimeError("grpc timeout")

        with self.assertRaises(GroupTypesUnavailable) as ctx:
            get_group_types_for_projects(self.project_ids)

        assert set(ctx.exception.project_ids) == set(self.project_ids)

    @patch("posthog.models.group_type_mapping._fetch_group_types_for_projects_via_personhog")
    def test_empty_project_ids_returns_empty_dict_via_personhog(
        self,
        mock_fetch_personhog,
    ):
        mock_fetch_personhog.return_value = {}

        result = get_group_types_for_projects([])

        assert result == {}

    @patch("posthog.models.group_type_mapping._fetch_group_types_for_projects_via_personhog")
    def test_personhog_success_backfills_missing_project_ids_with_empty_lists(
        self,
        mock_fetch_personhog,
    ):
        mock_fetch_personhog.return_value = {
            1: [{"group_type": "organization", "group_type_index": 0}],
        }

        result = get_group_types_for_projects([1, 2, 3])

        assert result == {
            1: [{"group_type": "organization", "group_type_index": 0}],
            2: [],
            3: [],
        }


class TestGetGroupTypesForProjectCacheBehavior(SimpleTestCase):
    def setUp(self):
        self.project_id = 888
        _clear_cache(self.project_id)
        self._client_patcher = patch(_CLIENT_PATCH, return_value=MagicMock())
        self._client_patcher.start()

    def tearDown(self):
        self._client_patcher.stop()
        _clear_cache(self.project_id)

    @patch("posthog.models.group_type_mapping.GroupTypeMapping.objects")
    @patch("posthog.models.group_type_mapping._fetch_group_types_via_personhog")
    def test_empty_list_result_is_cached(
        self,
        mock_fetch_personhog,
        mock_objects,
    ):
        mock_fetch_personhog.return_value = []

        result1 = get_group_types_for_project(self.project_id)
        result2 = get_group_types_for_project(self.project_id)

        assert result1 == []
        assert result2 == []
        assert mock_fetch_personhog.call_count == 1

    @patch("posthog.models.group_type_mapping.GroupTypeMapping.objects")
    @patch("posthog.models.group_type_mapping._fetch_group_types_via_personhog")
    def test_personhog_success_populates_stale_cache(
        self,
        mock_fetch_personhog,
        mock_objects,
    ):
        from posthog.models.group_type_mapping import GROUP_TYPES_STALE_CACHE_KEY_PREFIX
        from posthog.utils import get_safe_cache

        mock_fetch_personhog.return_value = PERSONHOG_SUCCESS_DATA

        get_group_types_for_project(self.project_id)

        stale = get_safe_cache(f"{GROUP_TYPES_STALE_CACHE_KEY_PREFIX}{self.project_id}")
        assert stale == PERSONHOG_SUCCESS_DATA

    @patch("posthog.models.group_type_mapping.GroupTypeMapping.objects")
    @patch("posthog.models.group_type_mapping._fetch_group_types_via_personhog")
    def test_empty_success_does_not_clobber_populated_stale(
        self,
        mock_fetch_personhog,
        mock_objects,
    ):
        from posthog.utils import get_safe_cache

        # A populated last-known-good already exists (e.g. written by the batch path).
        stale_key = f"{GROUP_TYPES_STALE_CACHE_KEY_PREFIX}{self.project_id}"
        safe_cache_set(stale_key, PERSONHOG_SUCCESS_DATA, 3600)

        # Upstream succeeds but returns empty — the "empty-but-not-erroring" failure
        # mode the corruption guard depends on the stale fallback to catch.
        mock_fetch_personhog.return_value = []

        result = get_group_types_for_project(self.project_id)

        # The empty success is served, but must not erase the populated fallback.
        assert result == []
        assert get_safe_cache(stale_key) == PERSONHOG_SUCCESS_DATA


class TestGetGroupTypesForTeamEdgeCases(SimpleTestCase):
    def setUp(self):
        self._client_patcher = patch(_CLIENT_PATCH, return_value=MagicMock())
        self._client_patcher.start()

    def tearDown(self):
        self._client_patcher.stop()

    @patch("posthog.models.group_type_mapping.GroupTypeMapping.objects")
    @patch("posthog.models.group_type_mapping._fetch_group_types_for_team_via_personhog")
    def test_personhog_returns_empty_list(
        self,
        mock_fetch_personhog,
        mock_objects,
    ):
        mock_fetch_personhog.return_value = []

        result = get_group_types_for_team(42)

        assert result == []
        mock_objects.filter.assert_not_called()


class TestCountGroupTypeMappingsPerTeam(SimpleTestCase):
    def setUp(self):
        self._mock_client = MagicMock()
        self._client_patcher = patch(_CLIENT_PATCH, return_value=self._mock_client)
        self._client_patcher.start()

    def tearDown(self):
        self._client_patcher.stop()

    @patch("posthog.models.group_type_mapping.GroupTypeMapping.objects")
    def test_personhog_success_returns_converted_counts(
        self,
        mock_objects,
    ):
        mock_count_1 = MagicMock()
        mock_count_1.team_id = 1
        mock_count_1.count = 3
        mock_count_2 = MagicMock()
        mock_count_2.team_id = 2
        mock_count_2.count = 5

        mock_resp = MagicMock()
        mock_resp.counts = [mock_count_1, mock_count_2]
        self._mock_client.count_group_type_mappings.return_value = mock_resp

        result = count_group_type_mappings_per_team()

        assert result == [{"team_id": 1, "total": 3}, {"team_id": 2, "total": 5}]
        mock_objects.values.assert_not_called()

    def test_personhog_failure_returns_empty(
        self,
    ):
        self._mock_client.count_group_type_mappings.side_effect = RuntimeError("grpc timeout")

        result = count_group_type_mappings_per_team()

        assert result == []


# ── Write helper tests ─────────────────────────────────────────────


class TestUpdateGroupTypeMappingFields(SimpleTestCase):
    def _make_instance(self):
        instance = MagicMock()
        instance.project_id = 1
        instance.group_type_index = 0
        return instance

    def _mock_objects_filter(self):
        """Patch GroupTypeMapping.objects so a stray ORM call can't hit a real DB."""
        patcher = patch("posthog.models.group_type_mapping.GroupTypeMapping.objects")
        mock_objects = patcher.start()
        self.addCleanup(patcher.stop)
        return mock_objects

    @patch(_CLIENT_PATCH)
    def test_personhog_success_does_not_call_orm(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.update_group_type_mapping.return_value = MagicMock()
        mock_get_client.return_value = mock_client

        mock_objects = self._mock_objects_filter()

        instance = self._make_instance()
        update_group_type_mapping_fields(instance, fields={"name_singular": "Org", "name_plural": "Orgs"})

        mock_client.update_group_type_mapping.assert_called_once()
        req = mock_client.update_group_type_mapping.call_args[0][0]
        assert req.project_id == 1
        assert req.group_type_index == 0
        assert set(req.update_mask) == {"name_singular", "name_plural"}
        assert req.name_singular == "Org"
        assert req.name_plural == "Orgs"
        mock_objects.filter.assert_not_called()

    @patch(_CLIENT_PATCH)
    def test_detail_dashboard_id_sent_correctly(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.update_group_type_mapping.return_value = MagicMock()
        mock_get_client.return_value = mock_client

        instance = self._make_instance()
        update_group_type_mapping_fields(instance, fields={"detail_dashboard_id": 42})

        req = mock_client.update_group_type_mapping.call_args[0][0]
        assert req.detail_dashboard_id == 42
        assert "detail_dashboard_id" in req.update_mask

    @patch(_CLIENT_PATCH)
    def test_detail_dashboard_id_none_leaves_field_unset(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.update_group_type_mapping.return_value = MagicMock()
        mock_get_client.return_value = mock_client

        instance = self._make_instance()
        update_group_type_mapping_fields(instance, fields={"detail_dashboard_id": None})

        req = mock_client.update_group_type_mapping.call_args[0][0]
        assert "detail_dashboard_id" in req.update_mask
        assert req.detail_dashboard_id == 0

    @patch(_CLIENT_PATCH)
    def test_default_columns_json_encoded(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.update_group_type_mapping.return_value = MagicMock()
        mock_get_client.return_value = mock_client

        instance = self._make_instance()
        update_group_type_mapping_fields(instance, fields={"default_columns": ["name", "email"]})

        req = mock_client.update_group_type_mapping.call_args[0][0]
        assert b'"name"' in req.default_columns
        assert b'"email"' in req.default_columns


class TestDeleteGroupTypeMapping(SimpleTestCase):
    def _make_instance(self):
        instance = MagicMock()
        instance.project_id = 1
        instance.group_type_index = 0
        return instance

    @patch(_CLIENT_PATCH)
    def test_personhog_success_does_not_call_orm_delete(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.delete_group_type_mapping.return_value = MagicMock()
        mock_get_client.return_value = mock_client

        instance = self._make_instance()
        delete_group_type_mapping(instance)

        mock_client.delete_group_type_mapping.assert_called_once()
        req = mock_client.delete_group_type_mapping.call_args[0][0]
        assert req.project_id == 1
        assert req.group_type_index == 0
        instance.delete.assert_not_called()


class TestClearDashboardFromGroupTypeMapping(SimpleTestCase):
    @patch("posthog.models.group_type_mapping.invalidate_group_types_cache")
    @patch(_CLIENT_PATCH)
    def test_personhog_success_reads_then_updates(self, mock_get_client, mock_invalidate):
        mock_mapping = MagicMock()
        mock_mapping.project_id = 1
        mock_mapping.group_type_index = 0
        mock_resp = MagicMock()
        mock_resp.mapping = mock_mapping

        mock_client = MagicMock()
        mock_client.get_group_type_mapping_by_dashboard_id.return_value = mock_resp
        mock_client.update_group_type_mapping.return_value = MagicMock()
        mock_get_client.return_value = mock_client

        clear_dashboard_from_group_type_mapping(team_id=10, dashboard_id=42)

        mock_client.get_group_type_mapping_by_dashboard_id.assert_called_once()
        mock_client.update_group_type_mapping.assert_called_once()
        update_req = mock_client.update_group_type_mapping.call_args[0][0]
        assert update_req.project_id == 1
        assert update_req.group_type_index == 0
        assert "detail_dashboard_id" in update_req.update_mask
        assert update_req.detail_dashboard_id == 0
        mock_invalidate.assert_called_once_with(1)

    @patch("posthog.models.group_type_mapping.invalidate_group_types_cache")
    @patch(_CLIENT_PATCH)
    def test_personhog_group_type_index_zero_still_clears(self, mock_get_client, mock_invalidate):
        """group_type_index=0 is falsy but valid — HasField must not skip it."""
        mock_mapping = MagicMock(spec=["project_id", "group_type_index"])
        mock_mapping.project_id = 1
        mock_mapping.group_type_index = 0

        mock_resp = MagicMock()
        mock_resp.HasField.return_value = True
        mock_resp.mapping = mock_mapping

        mock_client = MagicMock()
        mock_client.get_group_type_mapping_by_dashboard_id.return_value = mock_resp
        mock_client.update_group_type_mapping.return_value = MagicMock()
        mock_get_client.return_value = mock_client

        clear_dashboard_from_group_type_mapping(team_id=10, dashboard_id=42)

        mock_client.update_group_type_mapping.assert_called_once()
        update_req = mock_client.update_group_type_mapping.call_args[0][0]
        assert update_req.group_type_index == 0
        mock_invalidate.assert_called_once_with(1)

    @patch("posthog.models.group_type_mapping.invalidate_group_types_cache")
    @patch(_CLIENT_PATCH)
    def test_personhog_no_matching_mapping_skips_update(self, mock_get_client, mock_invalidate):
        mock_resp = MagicMock()
        mock_resp.HasField.return_value = False

        mock_client = MagicMock()
        mock_client.get_group_type_mapping_by_dashboard_id.return_value = mock_resp
        mock_get_client.return_value = mock_client

        clear_dashboard_from_group_type_mapping(team_id=10, dashboard_id=999)

        mock_client.update_group_type_mapping.assert_not_called()
        mock_invalidate.assert_not_called()


# ── Terminal-failure hardening tests ──────────────────────────────────


class TestTerminalFetchFailureMetric(SimpleTestCase):
    def setUp(self):
        self.project_id = 7777
        _clear_cache(self.project_id)
        self._client_patcher = patch(_CLIENT_PATCH, return_value=MagicMock())
        self._client_patcher.start()

    def tearDown(self):
        self._client_patcher.stop()
        _clear_cache(self.project_id)

    @patch("posthog.models.group_type_mapping.GROUP_TYPES_FETCH_FAILURES")
    @patch("posthog.models.group_type_mapping._fetch_group_types_via_personhog", side_effect=RuntimeError("grpc fail"))
    def test_single_project_failure_increments_fetch_failures(self, _mock_fetch, mock_fetch_failures):
        result = get_group_types_for_project(self.project_id)

        assert result == []
        mock_fetch_failures.labels.assert_called_once_with(
            operation="get_group_types_for_project", source="personhog", error_type="db_error"
        )

    @patch("posthog.models.group_type_mapping.GROUP_TYPES_FETCH_FAILURES")
    @patch(
        "posthog.models.group_type_mapping._fetch_group_types_for_team_via_personhog",
        side_effect=RuntimeError("grpc fail"),
    )
    def test_team_failure_increments_fetch_failures(self, _mock_fetch, mock_fetch_failures):
        result = get_group_types_for_team(4242)

        assert result == []
        mock_fetch_failures.labels.assert_called_once_with(
            operation="get_group_types_for_team", source="personhog", error_type="db_error"
        )

    @patch("posthog.models.group_type_mapping.GROUP_TYPES_FETCH_FAILURES")
    @patch(
        "posthog.models.group_type_mapping._fetch_group_types_for_projects_via_personhog",
        side_effect=RuntimeError("grpc fail"),
    )
    def test_projects_failure_increments_fetch_failures(self, _mock_fetch, mock_fetch_failures):
        with self.assertRaises(GroupTypesUnavailable):
            get_group_types_for_projects([self.project_id])

        mock_fetch_failures.labels.assert_called_once_with(
            operation="get_group_types_for_projects", source="personhog", error_type="db_error"
        )


class TestGetGroupTypesForProjectsFailClosed(SimpleTestCase):
    def setUp(self):
        self.project_ids = [101, 102]
        for pid in self.project_ids:
            _clear_cache(pid)
        self._client_patcher = patch(_CLIENT_PATCH, return_value=MagicMock())
        self._client_patcher.start()
        self._fetch_patcher = patch(
            "posthog.models.group_type_mapping._fetch_group_types_for_projects_via_personhog",
            side_effect=RuntimeError("grpc fail"),
        )
        self._fetch_patcher.start()

    def tearDown(self):
        self._fetch_patcher.stop()
        self._client_patcher.stop()
        for pid in self.project_ids:
            _clear_cache(pid)

    def test_recovers_each_project_from_stale(self):
        stale_101 = [{"group_type": "org", "group_type_index": 0}]
        stale_102 = [{"group_type": "company", "group_type_index": 0}]
        safe_cache_set(f"{GROUP_TYPES_STALE_CACHE_KEY_PREFIX}101", stale_101, 3600)
        safe_cache_set(f"{GROUP_TYPES_STALE_CACHE_KEY_PREFIX}102", stale_102, 3600)

        result = get_group_types_for_projects(self.project_ids)

        assert result == {101: stale_101, 102: stale_102}

    def test_raises_group_types_unavailable_when_no_stale(self):
        with self.assertRaises(GroupTypesUnavailable) as ctx:
            get_group_types_for_projects(self.project_ids)

        assert set(ctx.exception.project_ids) == {101, 102}

    def test_raises_when_any_project_lacks_stale(self):
        safe_cache_set(f"{GROUP_TYPES_STALE_CACHE_KEY_PREFIX}101", [{"group_type": "org", "group_type_index": 0}], 3600)

        with self.assertRaises(GroupTypesUnavailable) as ctx:
            get_group_types_for_projects(self.project_ids)

        assert ctx.exception.project_ids == [102]

    def test_empty_stale_counts_as_recovered(self):
        safe_cache_set(f"{GROUP_TYPES_STALE_CACHE_KEY_PREFIX}101", [], 3600)
        safe_cache_set(f"{GROUP_TYPES_STALE_CACHE_KEY_PREFIX}102", [], 3600)

        result = get_group_types_for_projects(self.project_ids)

        assert result == {101: [], 102: []}


class TestRecordGroupTypesFetchFailureThrottle(SimpleTestCase):
    def setUp(self):
        self.operation = "get_group_types_for_projects"
        safe_cache_delete(f"group_types_failure_capture_throttle:{self.operation}")

    def tearDown(self):
        safe_cache_delete(f"group_types_failure_capture_throttle:{self.operation}")

    @patch("posthog.models.group_type_mapping.GROUP_TYPES_FETCH_FAILURES")
    @patch("posthog.models.group_type_mapping.logger")
    @patch("posthog.utils.capture_exception")
    def test_captures_once_then_logs_throttled(self, mock_capture, mock_logger, mock_counter):
        from django.db import DatabaseError

        exc = DatabaseError("db down")

        _record_group_types_fetch_failure(
            operation=self.operation, log_event="persons_db_group_types_for_projects_failure", exc=exc, project_ids=[1]
        )
        _record_group_types_fetch_failure(
            operation=self.operation, log_event="persons_db_group_types_for_projects_failure", exc=exc, project_ids=[1]
        )

        # Captured once across the throttle window, but the counter moves both times
        mock_capture.assert_called_once_with(exc)
        assert mock_counter.labels.call_count == 2

        first_kwargs = mock_logger.exception.call_args_list[0].kwargs
        second_kwargs = mock_logger.exception.call_args_list[1].kwargs
        assert first_kwargs["exception_captured"] is True
        assert first_kwargs["capture_throttled"] is False
        assert second_kwargs["exception_captured"] is False
        assert second_kwargs["capture_throttled"] is True


class TestProjectHasGroupTypesAuthoritatively(SimpleTestCase):
    _PROJECT_IDS = (123, 777, 888)
    _DIRECT_PATCH = "posthog.models.group_type_mapping._fetch_group_types_for_project_direct"
    _SAMPLE_ROW = {
        "group_type": "organization",
        "group_type_index": 0,
        "name_singular": None,
        "name_plural": None,
        "detail_dashboard": None,
        "default_columns": None,
        "created_at": None,
    }

    def setUp(self):
        self._clear_markers()

    def tearDown(self):
        self._clear_markers()

    def _clear_markers(self):
        for project_id in self._PROJECT_IDS:
            safe_cache_delete(f"{GROUP_TYPES_CONFIRMED_EMPTY_CACHE_KEY_PREFIX}{project_id}")

    @patch(_DIRECT_PATCH)
    def test_returns_true_when_rows_exist(self, mock_fetch):
        mock_fetch.return_value = [self._SAMPLE_ROW]

        assert project_has_group_types_authoritatively(123) is True
        mock_fetch.assert_called_once_with(123, "strong", caller_tag="flags/has-group-types")

    @patch(_DIRECT_PATCH)
    def test_returns_false_when_no_rows(self, mock_fetch):
        mock_fetch.return_value = []

        assert project_has_group_types_authoritatively(123) is False

    @patch(_DIRECT_PATCH)
    def test_fails_closed_on_db_error(self, mock_fetch):
        from django.db import DatabaseError

        mock_fetch.side_effect = DatabaseError("db down")

        assert project_has_group_types_authoritatively(123) is True

    @patch(_DIRECT_PATCH)
    def test_confirmed_empty_marker_short_circuits_second_call(self, mock_fetch):
        mock_fetch.return_value = []

        assert project_has_group_types_authoritatively(777) is False
        assert project_has_group_types_authoritatively(777) is False
        mock_fetch.assert_called_once()

    @patch(_DIRECT_PATCH)
    def test_present_result_is_not_cached(self, mock_fetch):
        mock_fetch.return_value = [self._SAMPLE_ROW]

        assert project_has_group_types_authoritatively(777) is True
        assert project_has_group_types_authoritatively(777) is True
        assert mock_fetch.call_count == 2

    def test_invalidate_group_types_cache_clears_confirmed_empty_marker(self):
        marker_key = f"{GROUP_TYPES_CONFIRMED_EMPTY_CACHE_KEY_PREFIX}888"
        safe_cache_set(marker_key, True, 300)

        invalidate_group_types_cache(888)

        assert get_safe_cache(marker_key) is None


class TestUnconfiguredClientDegradesGracefully(SimpleTestCase):
    """When PERSONHOG_ADDR is unset, get_personhog_client() returns None and
    require_personhog_client() raises RuntimeError. The singular read paths must treat
    that as a recoverable miss (like a DatabaseError), not let the RuntimeError escape
    the except-DatabaseError handlers and 500 the home, project, and events renders.
    """

    def setUp(self):
        self.project_id = 314159
        _clear_cache(self.project_id)
        self._client_patcher = patch(_CLIENT_PATCH, return_value=None)
        self._client_patcher.start()

    def tearDown(self):
        self._client_patcher.stop()
        _clear_cache(self.project_id)
        safe_cache_delete(f"{GROUP_TYPES_CONFIRMED_EMPTY_CACHE_KEY_PREFIX}{self.project_id}")

    @parameterized.expand(
        [
            ("project", lambda self: get_group_types_for_project(self.project_id)),
            ("team", lambda self: get_group_types_for_team(42)),
            ("count", lambda self: count_group_type_mappings_per_team()),
        ]
    )
    def test_read_path_returns_empty(self, _name, call):
        assert call(self) == []

    def test_project_has_group_types_fails_closed(self):
        # Unconfirmable state must not be treated as "safe to empty" — fail closed to True.
        assert project_has_group_types_authoritatively(self.project_id) is True


class TestDictToGroupTypeMappingModel(SimpleTestCase):
    def test_builds_model_from_full_dict(self):
        row = {
            "group_type": "organization",
            "group_type_index": 0,
            "name_singular": "Organization",
            "name_plural": "Organizations",
            "detail_dashboard": 42,
            "default_columns": ["name"],
            "created_at": None,
        }
        obj = _dict_to_group_type_mapping_model(row, project_id=99)

        assert obj.project_id == 99
        assert obj.group_type == "organization"
        assert obj.group_type_index == 0
        assert obj.name_singular == "Organization"
        assert obj.name_plural == "Organizations"
        assert obj.detail_dashboard_id == 42
        assert obj.default_columns == ["name"]
        assert obj._state.adding is False

    def test_builds_model_from_minimal_dict(self):
        row = {"group_type": "company", "group_type_index": 1}
        obj = _dict_to_group_type_mapping_model(row, project_id=99)

        assert obj.group_type == "company"
        assert obj.group_type_index == 1
        assert obj.name_singular is None
        assert obj.name_plural is None
        assert obj.detail_dashboard_id is None
        assert obj.default_columns is None
        assert obj._state.adding is False

    def test_accepts_detail_dashboard_id_key(self):
        row = {"group_type": "org", "group_type_index": 0, "detail_dashboard_id": 7}
        obj = _dict_to_group_type_mapping_model(row, project_id=99)

        assert obj.detail_dashboard_id == 7

    def test_team_none_by_default(self):
        row = {"group_type": "org", "group_type_index": 0}
        obj = _dict_to_group_type_mapping_model(row, project_id=99)

        assert obj.team_id is None


class TestGetGroupTypeMappingInstance(SimpleTestCase):
    def setUp(self):
        self.project_id = 777
        _clear_cache(self.project_id)

    def tearDown(self):
        _clear_cache(self.project_id)

    @patch("posthog.models.group_type_mapping.get_group_types_for_project")
    def test_returns_matching_instance(self, mock_get):
        mock_get.return_value = PERSONHOG_SUCCESS_DATA

        result = get_group_type_mapping_instance(self.project_id, 0)

        assert isinstance(result, GroupTypeMapping)
        assert result.group_type == "organization"
        assert result.group_type_index == 0
        assert result.project_id == self.project_id
        mock_get.assert_called_once_with(self.project_id, caller_tag=None)

    @patch("posthog.models.group_type_mapping.get_group_types_for_project")
    def test_returns_second_index(self, mock_get):
        mock_get.return_value = PERSONHOG_SUCCESS_DATA

        result = get_group_type_mapping_instance(self.project_id, 1)

        assert result.group_type == "company"
        assert result.group_type_index == 1

    @patch("posthog.models.group_type_mapping.invalidate_group_types_cache")
    @patch("posthog.models.group_type_mapping.get_group_types_for_project")
    def test_cache_bust_retry_finds_mapping(self, mock_get, mock_invalidate):
        fresh_data = [
            *PERSONHOG_SUCCESS_DATA,
            {
                "group_type": "workspace",
                "group_type_index": 2,
                "name_singular": "Workspace",
                "name_plural": "Workspaces",
                "detail_dashboard": None,
                "default_columns": None,
                "created_at": None,
            },
        ]
        mock_get.side_effect = [PERSONHOG_SUCCESS_DATA, fresh_data]

        result = get_group_type_mapping_instance(self.project_id, 2)

        assert result.group_type == "workspace"
        assert result.group_type_index == 2
        mock_invalidate.assert_called_once_with(self.project_id)
        assert mock_get.call_count == 2

    @patch("posthog.models.group_type_mapping.invalidate_group_types_cache")
    @patch("posthog.models.group_type_mapping.get_group_types_for_project")
    def test_raises_does_not_exist_after_retry(self, mock_get, mock_invalidate):
        mock_get.return_value = PERSONHOG_SUCCESS_DATA

        with self.assertRaises(GroupTypeMapping.DoesNotExist):
            get_group_type_mapping_instance(self.project_id, 99)

        mock_invalidate.assert_called_once_with(self.project_id)
        assert mock_get.call_count == 2

    @patch("posthog.models.group_type_mapping._dict_to_group_type_mapping_model")
    @patch("posthog.models.group_type_mapping.get_group_types_for_project")
    def test_passes_team_to_model_builder(self, mock_get, mock_builder):
        mock_get.return_value = PERSONHOG_SUCCESS_DATA
        mock_builder.return_value = MagicMock(spec=GroupTypeMapping)
        team = MagicMock()

        get_group_type_mapping_instance(self.project_id, 0, team=team)

        mock_builder.assert_called_once_with(PERSONHOG_SUCCESS_DATA[0], project_id=self.project_id, team=team)

    @patch("posthog.models.group_type_mapping._fetch_group_types_for_project_direct")
    def test_consistency_strong_bypasses_cache(self, mock_fetch):
        mock_fetch.return_value = PERSONHOG_SUCCESS_DATA
        mock_builder_result = MagicMock(spec=GroupTypeMapping)

        with patch(
            "posthog.models.group_type_mapping._dict_to_group_type_mapping_model", return_value=mock_builder_result
        ):
            result = get_group_type_mapping_instance(self.project_id, 0, consistency="strong")

        assert result is mock_builder_result
        mock_fetch.assert_called_once()

    @patch("posthog.models.group_type_mapping._fetch_group_types_for_project_direct")
    def test_consistency_strong_raises_does_not_exist(self, mock_fetch):
        mock_fetch.return_value = PERSONHOG_SUCCESS_DATA

        with self.assertRaises(GroupTypeMapping.DoesNotExist):
            get_group_type_mapping_instance(self.project_id, 99, consistency="strong")
