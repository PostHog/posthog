from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.group_type_mapping import (
    GROUP_TYPES_CACHE_KEY_PREFIX,
    GROUP_TYPES_STALE_CACHE_KEY_PREFIX,
    clear_dashboard_from_group_type_mapping,
    delete_group_type_mapping,
    get_group_types_for_project,
    get_group_types_for_projects,
    get_group_types_for_team,
    update_group_type_mapping_fields,
)
from posthog.utils import safe_cache_delete


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
        self._client_patcher = patch(_CLIENT_PATCH, return_value=MagicMock())
        self._client_patcher.start()

    def tearDown(self):
        self._client_patcher.stop()

    @patch("posthog.models.group_type_mapping.GroupTypeMapping.objects")
    @patch("posthog.models.group_type_mapping._fetch_group_types_for_projects_via_personhog")
    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_TOTAL")
    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_ERRORS_TOTAL")
    def test_orm_database_error_returns_empty_dicts(
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

        result = get_group_types_for_projects([10, 20])

        assert result == {10: [], 20: []}


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
