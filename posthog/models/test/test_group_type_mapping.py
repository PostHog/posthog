from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.group_type_mapping import (
    GROUP_TYPES_CACHE_KEY_PREFIX,
    GROUP_TYPES_CONFIRMED_EMPTY_CACHE_KEY_PREFIX,
    GROUP_TYPES_STALE_CACHE_KEY_PREFIX,
    GroupTypesUnavailable,
    _record_group_types_fetch_failure,
    clear_dashboard_from_group_type_mapping,
    count_group_type_mappings_per_team,
    delete_group_type_mapping,
    get_group_types_for_project,
    get_group_types_for_projects,
    get_group_types_for_team,
    invalidate_group_types_cache,
    project_has_group_types_authoritatively,
    update_group_type_mapping_fields,
)
from posthog.person_db_router import PERSONS_DB_FOR_WRITE
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
        "detail_dashboard_id": None,
        "default_columns": ["name"],
        "created_at": None,
    },
    {
        "group_type": "company",
        "group_type_index": 1,
        "name_singular": None,
        "name_plural": None,
        "detail_dashboard_id": None,
        "default_columns": None,
        "created_at": None,
    },
]

ORM_DATA = [
    {
        "group_type": "team",
        "group_type_index": 0,
        "name_singular": None,
        "name_plural": None,
        "detail_dashboard_id": None,
        "default_columns": None,
        "created_at": None,
    },
]


_CLIENT_PATCH = "posthog.personhog_client.client.get_personhog_client"


class TestGetGroupTypesForProjectRouting(SimpleTestCase):
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
    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_TOTAL")
    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_ERRORS_TOTAL")
    def test_personhog_success_returns_data_and_caches(
        self,
        mock_errors_counter,
        mock_routing_counter,
        mock_fetch_personhog,
        mock_objects,
    ):
        mock_fetch_personhog.return_value = PERSONHOG_SUCCESS_DATA

        result = get_group_types_for_project(self.project_id)

        assert len(result) == 2
        mock_objects.filter.assert_not_called()
        mock_routing_counter.labels.assert_called_with(
            operation="get_group_types_for_project", source="personhog", client_name="posthog-django"
        )
        mock_errors_counter.labels.assert_not_called()

    @patch("posthog.models.group_type_mapping.GroupTypeMapping.objects")
    @patch("posthog.models.group_type_mapping._fetch_group_types_via_personhog")
    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_TOTAL")
    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_ERRORS_TOTAL")
    def test_personhog_failure_falls_back_to_orm(
        self,
        mock_errors_counter,
        mock_routing_counter,
        mock_fetch_personhog,
        mock_objects,
    ):
        mock_fetch_personhog.side_effect = RuntimeError("grpc timeout")

        mock_qs = MagicMock()
        mock_qs.order_by.return_value.values.return_value = ORM_DATA
        mock_objects.filter.return_value = mock_qs

        result = get_group_types_for_project(self.project_id)

        assert result == ORM_DATA
        mock_routing_counter.labels.assert_called_with(
            operation="get_group_types_for_project", source="django_orm", client_name="posthog-django"
        )
        mock_errors_counter.labels.assert_called_once()

    @patch("posthog.models.group_type_mapping.GroupTypeMapping.objects")
    def test_cache_hit_skips_both_paths(self, mock_objects):
        from posthog.utils import safe_cache_set

        cached_data = [{"group_type": "cached", "group_type_index": 0}]
        safe_cache_set(f"{GROUP_TYPES_CACHE_KEY_PREFIX}{self.project_id}", cached_data, 60)

        result = get_group_types_for_project(self.project_id)

        assert result == cached_data
        mock_objects.filter.assert_not_called()

    @patch("posthog.models.group_type_mapping.GroupTypeMapping.objects")
    @patch("posthog.models.group_type_mapping._fetch_group_types_via_personhog")
    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_TOTAL")
    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_ERRORS_TOTAL")
    def test_both_paths_fail_returns_stale_cache(
        self,
        mock_errors_counter,
        mock_routing_counter,
        mock_fetch_personhog,
        mock_objects,
    ):
        from django.db import DatabaseError

        from posthog.utils import safe_cache_set

        stale_data = [{"group_type": "stale", "group_type_index": 0}]
        safe_cache_set(f"{GROUP_TYPES_STALE_CACHE_KEY_PREFIX}{self.project_id}", stale_data, 3600)

        mock_fetch_personhog.side_effect = RuntimeError("grpc timeout")

        # The code calls list(qs.filter(...).order_by(...).values(...))
        # so we need __iter__ on the values() result to raise DatabaseError
        def _raise_db_error():
            raise DatabaseError("db is down")

        mock_values_qs = MagicMock()
        mock_values_qs.__iter__ = MagicMock(side_effect=_raise_db_error)
        mock_qs = MagicMock()
        mock_qs.order_by.return_value.values.return_value = mock_values_qs
        mock_objects.filter.return_value = mock_qs

        result = get_group_types_for_project(self.project_id)

        assert result == stale_data

    @patch("posthog.models.group_type_mapping.GroupTypeMapping.objects")
    @patch("posthog.models.group_type_mapping._fetch_group_types_via_personhog")
    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_TOTAL")
    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_ERRORS_TOTAL")
    def test_both_paths_fail_no_stale_returns_empty_list(
        self,
        mock_errors_counter,
        mock_routing_counter,
        mock_fetch_personhog,
        mock_objects,
    ):
        from django.db import DatabaseError

        mock_fetch_personhog.side_effect = RuntimeError("grpc timeout")

        def _raise_db_error():
            raise DatabaseError("db is down")

        mock_values_qs = MagicMock()
        mock_values_qs.__iter__ = MagicMock(side_effect=_raise_db_error)
        mock_qs = MagicMock()
        mock_qs.order_by.return_value.values.return_value = mock_values_qs
        mock_objects.filter.return_value = mock_qs

        result = get_group_types_for_project(self.project_id)

        assert result == []


class TestGetGroupTypesForTeamRouting(SimpleTestCase):
    def setUp(self):
        self.team_id = 42
        self._client_patcher = patch(_CLIENT_PATCH, return_value=MagicMock())
        self._client_patcher.start()

    def tearDown(self):
        self._client_patcher.stop()

    @patch("posthog.models.group_type_mapping.GroupTypeMapping.objects")
    @patch("posthog.models.group_type_mapping._fetch_group_types_for_team_via_personhog")
    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_TOTAL")
    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_ERRORS_TOTAL")
    def test_personhog_success_returns_data_without_orm(
        self,
        mock_errors_counter,
        mock_routing_counter,
        mock_fetch_personhog,
        mock_objects,
    ):
        mock_fetch_personhog.return_value = PERSONHOG_SUCCESS_DATA

        result = get_group_types_for_team(self.team_id)

        assert result == PERSONHOG_SUCCESS_DATA
        mock_objects.filter.assert_not_called()
        mock_routing_counter.labels.assert_called_with(
            operation="get_group_types_for_team", source="personhog", client_name="posthog-django"
        )
        mock_errors_counter.labels.assert_not_called()

    @patch("posthog.models.group_type_mapping.GroupTypeMapping.objects")
    @patch("posthog.models.group_type_mapping._fetch_group_types_for_team_via_personhog")
    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_TOTAL")
    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_ERRORS_TOTAL")
    def test_personhog_failure_falls_back_to_orm(
        self,
        mock_errors_counter,
        mock_routing_counter,
        mock_fetch_personhog,
        mock_objects,
    ):
        mock_fetch_personhog.side_effect = RuntimeError("grpc timeout")

        mock_qs = MagicMock()
        mock_qs.order_by.return_value.values.return_value = ORM_DATA
        mock_objects.filter.return_value = mock_qs

        result = get_group_types_for_team(self.team_id)

        assert result == ORM_DATA
        mock_errors_counter.labels.assert_called_once_with(
            operation="get_group_types_for_team",
            source="personhog",
            error_type="grpc_error",
            client_name="posthog-django",
        )

    @parameterized.expand(
        [
            ("grpc_error", RuntimeError("grpc timeout")),
            ("connection_error", ConnectionError("connection refused")),
            ("generic_error", Exception("unexpected")),
        ]
    )
    @patch("posthog.models.group_type_mapping.GroupTypeMapping.objects")
    @patch("posthog.models.group_type_mapping._fetch_group_types_for_team_via_personhog")
    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_TOTAL")
    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_ERRORS_TOTAL")
    def test_error_types_always_increment_error_metric(
        self,
        _name,
        exception,
        mock_errors_counter,
        mock_routing_counter,
        mock_fetch_personhog,
        mock_objects,
    ):
        mock_fetch_personhog.side_effect = exception
        mock_qs = MagicMock()
        mock_qs.order_by.return_value.values.return_value = ORM_DATA
        mock_objects.filter.return_value = mock_qs

        get_group_types_for_team(self.team_id)

        mock_errors_counter.labels.assert_called_once()

    @patch("posthog.models.group_type_mapping.GroupTypeMapping.objects")
    @patch("posthog.models.group_type_mapping._fetch_group_types_for_team_via_personhog")
    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_TOTAL")
    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_ERRORS_TOTAL")
    def test_orm_fallback_increments_django_orm_metric(
        self,
        mock_errors_counter,
        mock_routing_counter,
        mock_fetch_personhog,
        mock_objects,
    ):
        mock_fetch_personhog.side_effect = RuntimeError("grpc timeout")

        mock_qs = MagicMock()
        mock_qs.order_by.return_value.values.return_value = ORM_DATA
        mock_objects.filter.return_value = mock_qs

        get_group_types_for_team(self.team_id)

        calls = [str(c) for c in mock_routing_counter.labels.call_args_list]
        assert any("django_orm" in c for c in calls), f"Expected django_orm routing label, got: {calls}"


class TestGetGroupTypesForProjectsRouting(SimpleTestCase):
    def setUp(self):
        self.project_ids = [1, 2, 3]
        self._client_patcher = patch(_CLIENT_PATCH, return_value=MagicMock())
        self._client_patcher.start()

    def tearDown(self):
        self._client_patcher.stop()

    @patch("posthog.models.group_type_mapping.GroupTypeMapping.objects")
    @patch("posthog.models.group_type_mapping._fetch_group_types_for_projects_via_personhog")
    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_TOTAL")
    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_ERRORS_TOTAL")
    def test_personhog_success_returns_grouped_data_without_orm(
        self,
        mock_errors_counter,
        mock_routing_counter,
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
        mock_routing_counter.labels.assert_called_with(
            operation="get_group_types_for_projects", source="personhog", client_name="posthog-django"
        )
        mock_errors_counter.labels.assert_not_called()

    @patch("posthog.models.group_type_mapping.GroupTypeMapping.objects")
    @patch("posthog.models.group_type_mapping._fetch_group_types_for_projects_via_personhog")
    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_TOTAL")
    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_ERRORS_TOTAL")
    def test_personhog_failure_falls_back_to_orm(
        self,
        mock_errors_counter,
        mock_routing_counter,
        mock_fetch_personhog,
        mock_objects,
    ):
        mock_fetch_personhog.side_effect = RuntimeError("grpc timeout")

        orm_rows = [
            {
                "project_id": 1,
                "group_type": "organization",
                "group_type_index": 0,
                "name_singular": None,
                "name_plural": None,
                "detail_dashboard": None,
                "default_columns": None,
                "created_at": None,
            },
            {
                "project_id": 2,
                "group_type": "company",
                "group_type_index": 0,
                "name_singular": None,
                "name_plural": None,
                "detail_dashboard": None,
                "default_columns": None,
                "created_at": None,
            },
        ]
        mock_qs = MagicMock()
        mock_qs.order_by.return_value.values.return_value = [dict(r) for r in orm_rows]
        mock_objects.filter.return_value = mock_qs

        result = get_group_types_for_projects(self.project_ids)

        assert 1 in result
        assert 2 in result
        assert 3 in result
        assert result[3] == []
        mock_errors_counter.labels.assert_called_once_with(
            operation="get_group_types_for_projects",
            source="personhog",
            error_type="grpc_error",
            client_name="posthog-django",
        )

    @patch("posthog.models.group_type_mapping._fetch_group_types_for_projects_via_personhog")
    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_TOTAL")
    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_ERRORS_TOTAL")
    def test_empty_project_ids_returns_empty_dict_via_personhog(
        self,
        mock_errors_counter,
        mock_routing_counter,
        mock_fetch_personhog,
    ):
        mock_fetch_personhog.return_value = {}

        result = get_group_types_for_projects([])

        assert result == {}
        mock_errors_counter.labels.assert_not_called()

    @patch("posthog.models.group_type_mapping.GroupTypeMapping.objects")
    @patch("posthog.models.group_type_mapping._fetch_group_types_for_projects_via_personhog")
    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_TOTAL")
    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_ERRORS_TOTAL")
    def test_orm_fallback_initializes_all_project_ids_to_empty_list(
        self,
        mock_errors_counter,
        mock_routing_counter,
        mock_fetch_personhog,
        mock_objects,
    ):
        mock_fetch_personhog.side_effect = RuntimeError("grpc timeout")

        mock_qs = MagicMock()
        mock_qs.order_by.return_value.values.return_value = []
        mock_objects.filter.return_value = mock_qs

        result = get_group_types_for_projects([10, 20, 30])

        assert result == {10: [], 20: [], 30: []}

    @patch("posthog.models.group_type_mapping._fetch_group_types_for_projects_via_personhog")
    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_TOTAL")
    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_ERRORS_TOTAL")
    def test_personhog_success_backfills_missing_project_ids_with_empty_lists(
        self,
        mock_errors_counter,
        mock_routing_counter,
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
    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_TOTAL")
    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_ERRORS_TOTAL")
    def test_empty_list_result_is_cached(
        self,
        mock_errors_counter,
        mock_routing_counter,
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
    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_TOTAL")
    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_ERRORS_TOTAL")
    def test_personhog_success_populates_stale_cache(
        self,
        mock_errors_counter,
        mock_routing_counter,
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
    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_TOTAL")
    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_ERRORS_TOTAL")
    def test_empty_success_does_not_clobber_populated_stale(
        self,
        mock_errors_counter,
        mock_routing_counter,
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
    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_TOTAL")
    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_ERRORS_TOTAL")
    def test_personhog_returns_empty_list(
        self,
        mock_errors_counter,
        mock_routing_counter,
        mock_fetch_personhog,
        mock_objects,
    ):
        mock_fetch_personhog.return_value = []

        result = get_group_types_for_team(42)

        assert result == []
        mock_objects.filter.assert_not_called()

    @patch("posthog.models.group_type_mapping.GroupTypeMapping.objects")
    @patch("posthog.models.group_type_mapping._fetch_group_types_for_team_via_personhog")
    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_TOTAL")
    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_ERRORS_TOTAL")
    def test_orm_database_error_returns_empty_list(
        self,
        mock_errors_counter,
        mock_routing_counter,
        mock_fetch_personhog,
        mock_objects,
    ):
        from django.db import DatabaseError

        mock_fetch_personhog.side_effect = RuntimeError("grpc timeout")

        def _raise_db_error():
            raise DatabaseError("db is down")

        mock_values_qs = MagicMock()
        mock_values_qs.__iter__ = MagicMock(side_effect=_raise_db_error)
        mock_qs = MagicMock()
        mock_qs.order_by.return_value.values.return_value = mock_values_qs
        mock_objects.filter.return_value = mock_qs

        result = get_group_types_for_team(42)

        assert result == []


class TestGetGroupTypesForProjectsEdgeCases(SimpleTestCase):
    def setUp(self):
        for pid in (10, 20):
            _clear_cache(pid)
        self._client_patcher = patch(_CLIENT_PATCH, return_value=MagicMock())
        self._client_patcher.start()

    def tearDown(self):
        self._client_patcher.stop()
        for pid in (10, 20):
            _clear_cache(pid)

    @patch("posthog.models.group_type_mapping.GroupTypeMapping.objects")
    @patch("posthog.models.group_type_mapping._fetch_group_types_for_projects_via_personhog")
    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_TOTAL")
    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_ERRORS_TOTAL")
    def test_orm_database_error_without_stale_fails_closed(
        self,
        mock_errors_counter,
        mock_routing_counter,
        mock_fetch_personhog,
        mock_objects,
    ):
        from django.db import DatabaseError

        mock_fetch_personhog.side_effect = RuntimeError("grpc timeout")

        def _raise_db_error():
            raise DatabaseError("db is down")

        mock_values_qs = MagicMock()
        mock_values_qs.__iter__ = MagicMock(side_effect=_raise_db_error)
        mock_qs = MagicMock()
        mock_qs.order_by.return_value.values.return_value = mock_values_qs
        mock_objects.filter.return_value = mock_qs

        # With no last-known-good, the batch fetch fails closed rather than
        # returning an all-empty mapping that would silently disable group flags.
        with self.assertRaises(GroupTypesUnavailable) as ctx:
            get_group_types_for_projects([10, 20])

        assert set(ctx.exception.project_ids) == {10, 20}


class TestCountGroupTypeMappingsPerTeam(SimpleTestCase):
    def setUp(self):
        self._client_patcher = patch(_CLIENT_PATCH, return_value=MagicMock())
        self._client_patcher.start()

    def tearDown(self):
        self._client_patcher.stop()

    @patch("posthog.models.group_type_mapping.GroupTypeMapping.objects")
    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_TOTAL")
    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_ERRORS_TOTAL")
    def test_personhog_success_returns_converted_counts(
        self,
        mock_errors_counter,
        mock_routing_counter,
        mock_objects,
    ):
        mock_count_1 = MagicMock()
        mock_count_1.team_id = 1
        mock_count_1.count = 3
        mock_count_2 = MagicMock()
        mock_count_2.team_id = 2
        mock_count_2.count = 5

        from posthog.personhog_client.client import get_personhog_client

        mock_client = get_personhog_client()
        mock_resp = MagicMock()
        mock_resp.counts = [mock_count_1, mock_count_2]
        mock_client.count_group_type_mappings.return_value = mock_resp

        result = count_group_type_mappings_per_team()

        assert result == [{"team_id": 1, "total": 3}, {"team_id": 2, "total": 5}]
        mock_objects.values.assert_not_called()
        mock_routing_counter.labels.assert_called_with(
            operation="count_group_type_mappings_per_team", source="personhog", client_name="posthog-django"
        )
        mock_errors_counter.labels.assert_not_called()

    @patch("posthog.models.group_type_mapping.GroupTypeMapping.objects")
    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_TOTAL")
    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_ERRORS_TOTAL")
    def test_personhog_failure_falls_back_to_orm(
        self,
        mock_errors_counter,
        mock_routing_counter,
        mock_objects,
    ):
        from posthog.personhog_client.client import get_personhog_client

        mock_client = get_personhog_client()
        mock_client.count_group_type_mappings.side_effect = RuntimeError("grpc timeout")

        orm_data = [{"team_id": 1, "total": 3}]
        mock_qs = MagicMock()
        mock_qs.annotate.return_value.order_by.return_value = orm_data
        mock_objects.values.return_value = mock_qs

        result = count_group_type_mappings_per_team()

        assert result == orm_data
        mock_errors_counter.labels.assert_called_once_with(
            operation="count_group_type_mappings_per_team",
            source="personhog",
            error_type="grpc_error",
            client_name="posthog-django",
        )

    @patch("posthog.models.group_type_mapping.GroupTypeMapping.objects")
    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_TOTAL")
    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_ERRORS_TOTAL")
    def test_no_client_uses_orm_directly(
        self,
        mock_errors_counter,
        mock_routing_counter,
        mock_objects,
    ):
        self._client_patcher.stop()
        no_client_patcher = patch(_CLIENT_PATCH, return_value=None)
        no_client_patcher.start()

        orm_data = [{"team_id": 10, "total": 2}]
        mock_qs = MagicMock()
        mock_qs.annotate.return_value.order_by.return_value = orm_data
        mock_objects.values.return_value = mock_qs

        result = count_group_type_mappings_per_team()

        assert result == orm_data
        mock_routing_counter.labels.assert_called_with(
            operation="count_group_type_mappings_per_team", source="django_orm", client_name="posthog-django"
        )
        mock_errors_counter.labels.assert_not_called()

        no_client_patcher.stop()
        self._client_patcher = patch(_CLIENT_PATCH, return_value=MagicMock())
        self._client_patcher.start()


# ── Write helper tests ─────────────────────────────────────────────


class TestUpdateGroupTypeMappingFields(SimpleTestCase):
    def _make_instance(self):
        instance = MagicMock()
        instance.project_id = 1
        instance.group_type_index = 0
        return instance

    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_TOTAL")
    @patch(_CLIENT_PATCH)
    def test_personhog_success_does_not_call_orm_save(self, mock_get_client, mock_routing_counter):
        mock_client = MagicMock()
        mock_client.update_group_type_mapping.return_value = MagicMock()
        mock_get_client.return_value = mock_client

        instance = self._make_instance()
        update_group_type_mapping_fields(instance, fields={"name_singular": "Org", "name_plural": "Orgs"})

        mock_client.update_group_type_mapping.assert_called_once()
        req = mock_client.update_group_type_mapping.call_args[0][0]
        assert req.project_id == 1
        assert req.group_type_index == 0
        assert set(req.update_mask) == {"name_singular", "name_plural"}
        assert req.name_singular == "Org"
        assert req.name_plural == "Orgs"
        instance.save.assert_not_called()
        mock_routing_counter.labels.assert_called_with(
            operation="group_type_update", source="personhog", client_name="posthog-django"
        )

    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_TOTAL")
    @patch(_CLIENT_PATCH)
    def test_client_none_falls_back_to_orm_save(self, mock_get_client, mock_routing_counter):
        mock_get_client.return_value = None

        instance = self._make_instance()
        update_group_type_mapping_fields(instance, fields={"name_singular": "Org"})

        instance.save.assert_called_once()
        mock_routing_counter.labels.assert_called_with(
            operation="group_type_update", source="django_orm", client_name="posthog-django"
        )

    @parameterized.expand(
        [
            ("grpc_timeout", RuntimeError("grpc timeout")),
            ("connection_error", ConnectionError("connection refused")),
        ]
    )
    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_ERRORS_TOTAL")
    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_TOTAL")
    @patch(_CLIENT_PATCH)
    def test_personhog_exception_falls_back_to_orm(
        self, _name, exception, mock_get_client, mock_routing_counter, mock_errors_counter
    ):
        mock_client = MagicMock()
        mock_client.update_group_type_mapping.side_effect = exception
        mock_get_client.return_value = mock_client

        instance = self._make_instance()
        update_group_type_mapping_fields(instance, fields={"name_singular": "Org"})

        instance.save.assert_called_once()
        mock_errors_counter.labels.assert_called_once_with(
            operation="group_type_update",
            source="personhog",
            error_type="grpc_error",
            client_name="posthog-django",
        )

    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_TOTAL")
    @patch(_CLIENT_PATCH)
    def test_orm_fallback_sets_fields_on_instance(self, mock_get_client, mock_routing_counter):
        mock_get_client.return_value = None

        instance = self._make_instance()
        update_group_type_mapping_fields(instance, fields={"name_singular": "Team", "default_columns": ["name"]})

        assert instance.name_singular == "Team"
        assert instance.default_columns == ["name"]
        instance.save.assert_called_once()

    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_TOTAL")
    @patch(_CLIENT_PATCH)
    def test_detail_dashboard_id_sent_correctly(self, mock_get_client, mock_routing_counter):
        mock_client = MagicMock()
        mock_client.update_group_type_mapping.return_value = MagicMock()
        mock_get_client.return_value = mock_client

        instance = self._make_instance()
        update_group_type_mapping_fields(instance, fields={"detail_dashboard_id": 42})

        req = mock_client.update_group_type_mapping.call_args[0][0]
        assert req.detail_dashboard_id == 42
        assert "detail_dashboard_id" in req.update_mask

    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_TOTAL")
    @patch(_CLIENT_PATCH)
    def test_detail_dashboard_id_none_leaves_field_unset(self, mock_get_client, mock_routing_counter):
        mock_client = MagicMock()
        mock_client.update_group_type_mapping.return_value = MagicMock()
        mock_get_client.return_value = mock_client

        instance = self._make_instance()
        update_group_type_mapping_fields(instance, fields={"detail_dashboard_id": None})

        req = mock_client.update_group_type_mapping.call_args[0][0]
        assert "detail_dashboard_id" in req.update_mask
        assert req.detail_dashboard_id == 0

    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_TOTAL")
    @patch(_CLIENT_PATCH)
    def test_default_columns_json_encoded(self, mock_get_client, mock_routing_counter):
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

    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_TOTAL")
    @patch(_CLIENT_PATCH)
    def test_personhog_success_does_not_call_orm_delete(self, mock_get_client, mock_routing_counter):
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
        mock_routing_counter.labels.assert_called_with(
            operation="delete_group_type_mapping", source="personhog", client_name="posthog-django"
        )

    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_TOTAL")
    @patch(_CLIENT_PATCH)
    def test_client_none_falls_back_to_orm_delete(self, mock_get_client, mock_routing_counter):
        mock_get_client.return_value = None

        instance = self._make_instance()
        delete_group_type_mapping(instance)

        instance.delete.assert_called_once()
        mock_routing_counter.labels.assert_called_with(
            operation="delete_group_type_mapping", source="django_orm", client_name="posthog-django"
        )

    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_ERRORS_TOTAL")
    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_TOTAL")
    @patch(_CLIENT_PATCH)
    def test_personhog_exception_falls_back_to_orm_delete(
        self, mock_get_client, mock_routing_counter, mock_errors_counter
    ):
        mock_client = MagicMock()
        mock_client.delete_group_type_mapping.side_effect = RuntimeError("grpc timeout")
        mock_get_client.return_value = mock_client

        instance = self._make_instance()
        delete_group_type_mapping(instance)

        instance.delete.assert_called_once()
        mock_errors_counter.labels.assert_called_once()


class TestClearDashboardFromGroupTypeMapping(SimpleTestCase):
    @patch("posthog.models.group_type_mapping.invalidate_group_types_cache")
    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_TOTAL")
    @patch(_CLIENT_PATCH)
    def test_personhog_success_reads_then_updates(self, mock_get_client, mock_routing_counter, mock_invalidate):
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
    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_TOTAL")
    @patch(_CLIENT_PATCH)
    def test_personhog_no_matching_mapping_skips_update(self, mock_get_client, mock_routing_counter, mock_invalidate):
        mock_resp = MagicMock()
        mock_resp.mapping = None

        mock_client = MagicMock()
        mock_client.get_group_type_mapping_by_dashboard_id.return_value = mock_resp
        mock_get_client.return_value = mock_client

        clear_dashboard_from_group_type_mapping(team_id=10, dashboard_id=999)

        mock_client.update_group_type_mapping.assert_not_called()
        mock_invalidate.assert_not_called()

    @patch("posthog.models.group_type_mapping.invalidate_group_types_cache")
    @patch("posthog.models.group_type_mapping.GroupTypeMapping.objects")
    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_TOTAL")
    @patch(_CLIENT_PATCH)
    def test_client_none_falls_back_to_orm(self, mock_get_client, mock_routing_counter, mock_objects, mock_invalidate):
        mock_get_client.return_value = None

        clear_dashboard_from_group_type_mapping(team_id=10, dashboard_id=42, project_id=1)

        mock_objects.using.assert_called_once()
        mock_invalidate.assert_called_once_with(1)
        mock_routing_counter.labels.assert_called_with(
            operation="clear_dashboard_from_group_type_mapping", source="django_orm", client_name="posthog-django"
        )

    @patch("posthog.models.group_type_mapping.GroupTypeMapping.objects")
    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_ERRORS_TOTAL")
    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_TOTAL")
    @patch(_CLIENT_PATCH)
    def test_personhog_exception_falls_back_to_orm(
        self, mock_get_client, mock_routing_counter, mock_errors_counter, mock_objects
    ):
        mock_client = MagicMock()
        mock_client.get_group_type_mapping_by_dashboard_id.side_effect = RuntimeError("grpc timeout")
        mock_get_client.return_value = mock_client

        clear_dashboard_from_group_type_mapping(team_id=10, dashboard_id=42, project_id=1)

        mock_objects.using.assert_called_once()
        mock_errors_counter.labels.assert_called_once()


# ── Terminal-failure hardening tests ──────────────────────────────────


def _make_db_error_objects() -> MagicMock:
    # GroupTypeMapping.objects mock whose .filter(...).order_by(...).values()
    # raises DatabaseError when iterated.
    from django.db import DatabaseError

    def _raise_db_error():
        raise DatabaseError("db is down")

    mock_values_qs = MagicMock()
    mock_values_qs.__iter__ = MagicMock(side_effect=_raise_db_error)
    mock_qs = MagicMock()
    mock_qs.order_by.return_value.values.return_value = mock_values_qs
    mock_objects = MagicMock()
    mock_objects.filter.return_value = mock_qs
    return mock_objects


class TestTerminalFetchFailureMetric(SimpleTestCase):
    def setUp(self):
        self.project_id = 7777
        _clear_cache(self.project_id)
        # client None skips the personhog leg, isolating the ORM failure
        self._client_patcher = patch(_CLIENT_PATCH, return_value=None)
        self._client_patcher.start()

    def tearDown(self):
        self._client_patcher.stop()
        _clear_cache(self.project_id)

    @patch("posthog.models.group_type_mapping.GroupTypeMapping.objects")
    @patch("posthog.models.group_type_mapping.GROUP_TYPES_FETCH_FAILURES")
    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_ERRORS_TOTAL")
    def test_single_project_db_error_increments_fetch_failures_not_personhog(
        self, mock_personhog_errors, mock_fetch_failures, mock_objects
    ):
        mock_objects.filter.side_effect = _make_db_error_objects().filter

        result = get_group_types_for_project(self.project_id)

        assert result == []
        mock_fetch_failures.labels.assert_called_once_with(
            operation="get_group_types_for_project", source="django_orm", error_type="db_error"
        )
        mock_personhog_errors.labels.assert_not_called()

    @patch("posthog.models.group_type_mapping.GroupTypeMapping.objects")
    @patch("posthog.models.group_type_mapping.GROUP_TYPES_FETCH_FAILURES")
    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_ERRORS_TOTAL")
    def test_team_db_error_increments_fetch_failures_not_personhog(
        self, mock_personhog_errors, mock_fetch_failures, mock_objects
    ):
        mock_objects.filter.side_effect = _make_db_error_objects().filter

        result = get_group_types_for_team(4242)

        assert result == []
        mock_fetch_failures.labels.assert_called_once_with(
            operation="get_group_types_for_team", source="django_orm", error_type="db_error"
        )
        mock_personhog_errors.labels.assert_not_called()

    @patch("posthog.models.group_type_mapping.GroupTypeMapping.objects")
    @patch("posthog.models.group_type_mapping.GROUP_TYPES_FETCH_FAILURES")
    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_ERRORS_TOTAL")
    def test_projects_db_error_increments_fetch_failures_not_personhog(
        self, mock_personhog_errors, mock_fetch_failures, mock_objects
    ):
        mock_objects.filter.side_effect = _make_db_error_objects().filter

        # No stale, so it fails closed, but the counter still fires first
        with self.assertRaises(GroupTypesUnavailable):
            get_group_types_for_projects([self.project_id])

        mock_fetch_failures.labels.assert_called_once_with(
            operation="get_group_types_for_projects", source="django_orm", error_type="db_error"
        )
        mock_personhog_errors.labels.assert_not_called()


class TestGetGroupTypesForProjectsFailClosed(SimpleTestCase):
    def setUp(self):
        self.project_ids = [101, 102]
        for pid in self.project_ids:
            _clear_cache(pid)
        self._client_patcher = patch(_CLIENT_PATCH, return_value=None)
        self._client_patcher.start()

    def tearDown(self):
        self._client_patcher.stop()
        for pid in self.project_ids:
            _clear_cache(pid)

    @patch("posthog.models.group_type_mapping.GroupTypeMapping.objects")
    def test_db_error_recovers_each_project_from_stale(self, mock_objects):
        mock_objects.filter.side_effect = _make_db_error_objects().filter

        stale_101 = [{"group_type": "org", "group_type_index": 0}]
        stale_102 = [{"group_type": "company", "group_type_index": 0}]
        safe_cache_set(f"{GROUP_TYPES_STALE_CACHE_KEY_PREFIX}101", stale_101, 3600)
        safe_cache_set(f"{GROUP_TYPES_STALE_CACHE_KEY_PREFIX}102", stale_102, 3600)

        result = get_group_types_for_projects(self.project_ids)

        assert result == {101: stale_101, 102: stale_102}

    @patch("posthog.models.group_type_mapping.GroupTypeMapping.objects")
    def test_db_error_raises_group_types_unavailable_when_no_stale(self, mock_objects):
        mock_objects.filter.side_effect = _make_db_error_objects().filter

        with self.assertRaises(GroupTypesUnavailable) as ctx:
            get_group_types_for_projects(self.project_ids)

        assert set(ctx.exception.project_ids) == {101, 102}

    @patch("posthog.models.group_type_mapping.GroupTypeMapping.objects")
    def test_db_error_raises_when_any_project_lacks_stale(self, mock_objects):
        mock_objects.filter.side_effect = _make_db_error_objects().filter

        # Only 101 has a last-known-good; 102 is unrecoverable, so it fails closed
        safe_cache_set(f"{GROUP_TYPES_STALE_CACHE_KEY_PREFIX}101", [{"group_type": "org", "group_type_index": 0}], 3600)

        with self.assertRaises(GroupTypesUnavailable) as ctx:
            get_group_types_for_projects(self.project_ids)

        assert ctx.exception.project_ids == [102]

    @patch("posthog.models.group_type_mapping.GroupTypeMapping.objects")
    def test_empty_stale_counts_as_recovered(self, mock_objects):
        # A cached empty list is a known value, so it recovers rather than failing closed
        mock_objects.filter.side_effect = _make_db_error_objects().filter

        safe_cache_set(f"{GROUP_TYPES_STALE_CACHE_KEY_PREFIX}101", [], 3600)
        safe_cache_set(f"{GROUP_TYPES_STALE_CACHE_KEY_PREFIX}102", [], 3600)

        result = get_group_types_for_projects(self.project_ids)

        assert result == {101: [], 102: []}


class TestProjectsStaleCachePopulation(SimpleTestCase):
    def setUp(self):
        self.project_ids = [201, 202]
        for pid in self.project_ids:
            _clear_cache(pid)
        self._client_patcher = patch(_CLIENT_PATCH, return_value=None)
        self._client_patcher.start()

    def tearDown(self):
        self._client_patcher.stop()
        for pid in self.project_ids:
            _clear_cache(pid)

    @patch("posthog.models.group_type_mapping.GroupTypeMapping.objects")
    def test_orm_success_writes_non_empty_to_stale_only(self, mock_objects):
        from posthog.utils import get_safe_cache

        orm_rows = [
            {"project_id": 201, "group_type": "organization", "group_type_index": 0},
        ]
        mock_qs = MagicMock()
        mock_qs.order_by.return_value.values.return_value = [dict(r) for r in orm_rows]
        mock_objects.filter.return_value = mock_qs

        result = get_group_types_for_projects(self.project_ids)

        # 201 had a mapping → persisted to stale; 202 was empty → stale left absent
        assert result[201] == [{"group_type": "organization", "group_type_index": 0}]
        assert result[202] == []
        assert get_safe_cache(f"{GROUP_TYPES_STALE_CACHE_KEY_PREFIX}201") == [
            {"group_type": "organization", "group_type_index": 0}
        ]
        assert get_safe_cache(f"{GROUP_TYPES_STALE_CACHE_KEY_PREFIX}202") is None

    @patch("posthog.models.group_type_mapping.GroupTypeMapping.objects")
    def test_empty_success_does_not_overwrite_existing_stale(self, mock_objects):
        from posthog.utils import get_safe_cache

        prior = [{"group_type": "organization", "group_type_index": 0}]
        safe_cache_set(f"{GROUP_TYPES_STALE_CACHE_KEY_PREFIX}201", prior, 3600)

        mock_qs = MagicMock()
        mock_qs.order_by.return_value.values.return_value = []  # empty success
        mock_objects.filter.return_value = mock_qs

        get_group_types_for_projects([201])

        # Empty result must not clobber the populated last-known-good
        assert get_safe_cache(f"{GROUP_TYPES_STALE_CACHE_KEY_PREFIX}201") == prior


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

    def setUp(self):
        self._clear_markers()

    def tearDown(self):
        self._clear_markers()

    def _clear_markers(self):
        for project_id in self._PROJECT_IDS:
            safe_cache_delete(f"{GROUP_TYPES_CONFIRMED_EMPTY_CACHE_KEY_PREFIX}{project_id}")

    @patch("posthog.models.group_type_mapping.GroupTypeMapping.objects")
    def test_returns_true_when_rows_exist(self, mock_objects):
        mock_objects.using.return_value.filter.return_value.exists.return_value = True

        assert project_has_group_types_authoritatively(123) is True
        # Reads the primary, not a replica, so a lagging read cannot fake a deletion.
        mock_objects.using.assert_called_once_with(PERSONS_DB_FOR_WRITE)
        mock_objects.using.return_value.filter.assert_called_once_with(project_id=123)

    @patch("posthog.models.group_type_mapping.GroupTypeMapping.objects")
    def test_returns_false_when_no_rows(self, mock_objects):
        mock_objects.using.return_value.filter.return_value.exists.return_value = False

        assert project_has_group_types_authoritatively(123) is False

    @patch("posthog.models.group_type_mapping.GroupTypeMapping.objects")
    def test_fails_closed_on_db_error(self, mock_objects):
        from django.db import DatabaseError

        mock_objects.using.return_value.filter.return_value.exists.side_effect = DatabaseError("db down")

        # Cannot confirm absence → assume present so the caller keeps the existing entry.
        assert project_has_group_types_authoritatively(123) is True

    @patch("posthog.models.group_type_mapping.GroupTypeMapping.objects")
    def test_confirmed_empty_marker_short_circuits_second_call(self, mock_objects):
        exists_mock = mock_objects.using.return_value.filter.return_value.exists
        exists_mock.return_value = False

        # First call confirms empty against the DB and caches the marker.
        assert project_has_group_types_authoritatively(777) is False
        # Second call reads the marker instead of probing the writer DB again.
        assert project_has_group_types_authoritatively(777) is False
        exists_mock.assert_called_once()

    @patch("posthog.models.group_type_mapping.GroupTypeMapping.objects")
    def test_present_result_is_not_cached(self, mock_objects):
        exists_mock = mock_objects.using.return_value.filter.return_value.exists
        exists_mock.return_value = True

        # A True is never cached, so a later deletion is seen on the next call.
        assert project_has_group_types_authoritatively(777) is True
        assert project_has_group_types_authoritatively(777) is True
        assert exists_mock.call_count == 2

    def test_invalidate_group_types_cache_clears_confirmed_empty_marker(self):
        marker_key = f"{GROUP_TYPES_CONFIRMED_EMPTY_CACHE_KEY_PREFIX}888"
        safe_cache_set(marker_key, True, 300)

        invalidate_group_types_cache(888)

        # A team adding its first group type must stop short-circuiting to False at once.
        assert get_safe_cache(marker_key) is None
