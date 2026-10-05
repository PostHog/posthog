from unittest.mock import MagicMock

from django.test import SimpleTestCase

from parameterized import parameterized

from products.data_quality.backend.facade.enums import SubjectType
from products.data_quality.backend.logic.permissions import authorized_subject_types

_WAREHOUSE_TABLES = {SubjectType.TABLE, SubjectType.POSTHOG_TABLE}
_WAREHOUSE_KINDS = _WAREHOUSE_TABLES | {SubjectType.VIEW}


class TestAuthorizedSubjectTypes(SimpleTestCase):
    @parameterized.expand(
        [
            ("per_kind_table_write", ["query:read", "warehouse_table:write"], True, _WAREHOUSE_TABLES),
            ("per_kind_view_read", ["query:read", "warehouse_view:read"], False, {SubjectType.VIEW}),
            ("per_kind_read_cannot_write", ["query:read", "warehouse_table:read"], True, set()),
            ("family_read", ["query:read", "warehouse_objects:read"], False, _WAREHOUSE_KINDS),
            ("family_write", ["query:read", "warehouse_objects:write"], True, _WAREHOUSE_KINDS),
            ("catalog_only", ["query:read", "data_catalog:write"], True, {SubjectType.METRIC}),
            ("family_does_not_reach_metrics", ["warehouse_objects:write"], False, _WAREHOUSE_KINDS),
            ("session_user", None, True, set(SubjectType)),
        ]
    )
    def test_a_scope_reaches_the_subject_kinds_it_names(
        self, _name: str, scopes: list[str] | None, write: bool, expected: set[SubjectType]
    ) -> None:
        access = MagicMock(team=None)
        access.check_access_level_for_resource.return_value = True

        assert authorized_subject_types(access, scopes, write=write) == frozenset(expected)
