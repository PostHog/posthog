from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.group_type_mapping import (
    GROUP_TYPES_CACHE_KEY_PREFIX,
    GROUP_TYPES_STALE_CACHE_KEY_PREFIX,
    get_group_types_for_project,
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


class TestGetGroupTypesForProjectRouting(SimpleTestCase):
    def setUp(self):
        self.project_id = 999
        _clear_cache(self.project_id)

    def tearDown(self):
        _clear_cache(self.project_id)

    @parameterized.expand(
        [
            (
                "personhog_success_returns_data_and_caches",
                True,
                PERSONHOG_SUCCESS_DATA,
                None,
                2,
                "personhog",
            ),
            (
                "personhog_failure_falls_back_to_orm",
                True,
                None,
                RuntimeError("grpc timeout"),
                0,
                "django_orm",
            ),
            (
                "gate_off_uses_orm_directly",
                False,
                None,
                None,
                0,
                "django_orm",
            ),
        ]
    )
    @patch("posthog.models.group_type_mapping.GroupTypeMapping.objects")
    @patch("posthog.models.group_type_mapping._fetch_group_types_via_personhog")
    @patch("posthog.personhog_client.gate.use_personhog")
    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_TOTAL")
    @patch("posthog.models.group_type_mapping.PERSONHOG_ROUTING_ERRORS_TOTAL")
    def test_routing(
        self,
        _name,
        gate_on,
        personhog_data,
        grpc_exception,
        expected_count,
        expected_source,
        mock_errors_counter,
        mock_routing_counter,
        mock_use_personhog,
        mock_fetch_personhog,
        mock_objects,
    ):
        mock_use_personhog.return_value = gate_on

        if personhog_data is not None:
            mock_fetch_personhog.return_value = personhog_data
        elif grpc_exception is not None:
            mock_fetch_personhog.side_effect = grpc_exception

        mock_qs = MagicMock()
        mock_qs.order_by.return_value.values.return_value = ORM_DATA
        mock_objects.filter.return_value = mock_qs

        result = get_group_types_for_project(self.project_id)

        if personhog_data is not None and gate_on:
            assert len(result) == expected_count
            mock_objects.filter.assert_not_called()
        else:
            assert result == ORM_DATA

        mock_routing_counter.labels.assert_called_with(operation="get_group_types_for_project", source=expected_source)

        if grpc_exception is not None and gate_on:
            mock_errors_counter.labels.assert_called_once()

    @patch("posthog.models.group_type_mapping.GroupTypeMapping.objects")
    @patch("posthog.personhog_client.gate.use_personhog")
    def test_cache_hit_skips_both_paths(self, mock_use_personhog, mock_objects):
        from posthog.utils import safe_cache_set

        cached_data = [{"group_type": "cached", "group_type_index": 0}]
        safe_cache_set(f"{GROUP_TYPES_CACHE_KEY_PREFIX}{self.project_id}", cached_data, 60)

        result = get_group_types_for_project(self.project_id)

        assert result == cached_data
        mock_use_personhog.assert_not_called()
        mock_objects.filter.assert_not_called()
