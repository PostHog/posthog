from types import SimpleNamespace

from unittest.mock import MagicMock, patch

from django.db import DatabaseError
from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.filters.utils import GroupTypeIndex
from posthog.models.group.util import (
    create_group,
    get_group_by_key,
    get_groups_by_identifiers,
    get_groups_by_type_indices,
    save_group,
)

# Patched at source because util.py uses lazy `from X import Y` inside each function body —
# there is no module-level binding on util to patch. If these move to top-level imports, patch at call site instead.
_CLIENT_PATCH = "posthog.personhog_client.client.get_personhog_client"
_CONVERTER_PATCH = "posthog.personhog_client.converters.proto_group_to_model"
_ROUTING_TOTAL_PATCH = "posthog.models.group.util.PERSONHOG_ROUTING_TOTAL"
_ROUTING_ERRORS_PATCH = "posthog.models.group.util.PERSONHOG_ROUTING_ERRORS_TOTAL"


def _make_proto_group(**kwargs) -> SimpleNamespace:
    defaults = {
        "id": 0,
        "team_id": 0,
        "group_type_index": 0,
        "group_key": "",
        "group_properties": b"",
        "created_at": 0,
        "properties_last_updated_at": b"",
        "properties_last_operation": b"",
        "version": 0,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class TestGetGroupByKey(SimpleTestCase):
    def setUp(self):
        self.team_id = 10
        self.group_type_index = 0
        self.group_key = "org:123"

    @patch(_ROUTING_TOTAL_PATCH)
    @patch(_CLIENT_PATCH)
    def test_personhog_client_none_falls_back_to_orm_silently(self, mock_get_client, mock_routing_counter):
        mock_get_client.return_value = None

        from posthog.models.group.group import Group

        with patch.object(Group, "objects") as mock_objects:
            mock_group = MagicMock(spec=Group)
            mock_objects.get.return_value = mock_group

            result = get_group_by_key(self.team_id, self.group_type_index, self.group_key)

            assert result is mock_group
            mock_routing_counter.labels.assert_called_once_with(
                operation="get_group_by_key", source="django_orm", client_name="posthog-django"
            )

    @patch(_ROUTING_ERRORS_PATCH)
    @patch(_ROUTING_TOTAL_PATCH)
    @patch(_CONVERTER_PATCH)
    @patch(_CLIENT_PATCH)
    def test_personhog_returns_group_converts_and_returns_model(
        self, mock_get_client, mock_convert, mock_routing_counter, mock_errors_counter
    ):
        proto_group = _make_proto_group(id=7, team_id=self.team_id, group_key=self.group_key)
        mock_response = MagicMock()
        mock_response.group = proto_group
        mock_client = MagicMock()
        mock_client.get_group.return_value = mock_response
        mock_get_client.return_value = mock_client

        fake_model = MagicMock()
        mock_convert.return_value = fake_model

        result = get_group_by_key(self.team_id, self.group_type_index, self.group_key)

        assert result is fake_model
        mock_convert.assert_called_once_with(proto_group)
        mock_routing_counter.labels.assert_called_with(
            operation="get_group_by_key", source="personhog", client_name="posthog-django"
        )
        mock_errors_counter.labels.assert_not_called()

    @patch(_ROUTING_ERRORS_PATCH)
    @patch(_ROUTING_TOTAL_PATCH)
    @patch(_CLIENT_PATCH)
    def test_personhog_returns_group_with_zero_id_returns_none(
        self, mock_get_client, mock_routing_counter, mock_errors_counter
    ):
        proto_group = _make_proto_group(id=0, team_id=self.team_id, group_key=self.group_key)
        mock_response = MagicMock()
        mock_response.group = proto_group
        mock_client = MagicMock()
        mock_client.get_group.return_value = mock_response
        mock_get_client.return_value = mock_client

        result = get_group_by_key(self.team_id, self.group_type_index, self.group_key)

        assert result is None
        mock_routing_counter.labels.assert_called_with(
            operation="get_group_by_key", source="personhog", client_name="posthog-django"
        )

    @parameterized.expand(
        [
            ("grpc_timeout", RuntimeError("grpc timeout")),
            ("connection_error", ConnectionError("connection refused")),
            ("generic_exception", Exception("unexpected error")),
        ]
    )
    @patch(_ROUTING_ERRORS_PATCH)
    @patch(_ROUTING_TOTAL_PATCH)
    @patch(_CLIENT_PATCH)
    def test_personhog_exception_falls_back_to_orm(
        self, _name, exception, mock_get_client, mock_routing_counter, mock_errors_counter
    ):
        mock_client = MagicMock()
        mock_client.get_group.side_effect = exception
        mock_get_client.return_value = mock_client

        from posthog.models.group.group import Group

        with patch.object(Group, "objects") as mock_objects:
            mock_group = MagicMock(spec=Group)
            mock_objects.get.return_value = mock_group

            result = get_group_by_key(self.team_id, self.group_type_index, self.group_key)

            assert result is mock_group
            mock_errors_counter.labels.assert_called_once_with(
                operation="get_group_by_key",
                source="personhog",
                error_type="grpc_error",
                client_name="posthog-django",
            )
            calls = [str(c) for c in mock_routing_counter.labels.call_args_list]
            assert any("django_orm" in c for c in calls)

    @patch(_ROUTING_ERRORS_PATCH)
    @patch(_ROUTING_TOTAL_PATCH)
    @patch(_CLIENT_PATCH)
    def test_orm_fallback_does_not_exist_returns_none(self, mock_get_client, mock_routing_counter, mock_errors_counter):
        mock_client = MagicMock()
        mock_client.get_group.side_effect = RuntimeError("grpc timeout")
        mock_get_client.return_value = mock_client

        from posthog.models.group.group import Group

        with patch.object(Group, "objects") as mock_objects:
            mock_objects.get.side_effect = Group.DoesNotExist

            result = get_group_by_key(self.team_id, self.group_type_index, self.group_key)

            assert result is None


class TestGetGroupsByIdentifiers(SimpleTestCase):
    def setUp(self):
        self.team_id = 10
        self.group_type_index = 0

    def test_empty_group_keys_returns_empty_list_without_personhog(self):
        with patch(_CLIENT_PATCH) as mock_get_client:
            result = get_groups_by_identifiers(self.team_id, self.group_type_index, [])

            assert result == []
            mock_get_client.assert_not_called()

    @patch(_ROUTING_ERRORS_PATCH)
    @patch(_ROUTING_TOTAL_PATCH)
    @patch(_CONVERTER_PATCH)
    @patch(_CLIENT_PATCH)
    def test_personhog_success_returns_converted_models(
        self, mock_get_client, mock_convert, mock_routing_counter, mock_errors_counter
    ):
        proto_g1 = _make_proto_group(id=1, team_id=self.team_id, group_key="k1")
        proto_g2 = _make_proto_group(id=2, team_id=self.team_id, group_key="k2")

        mock_response = MagicMock()
        mock_response.groups = [proto_g1, proto_g2]
        mock_client = MagicMock()
        mock_client.get_groups.return_value = mock_response
        mock_get_client.return_value = mock_client

        model1 = MagicMock()
        model2 = MagicMock()
        mock_convert.side_effect = [model1, model2]

        result = get_groups_by_identifiers(self.team_id, self.group_type_index, ["k1", "k2"])

        assert result == [model1, model2]
        mock_routing_counter.labels.assert_called_with(
            operation="get_groups_by_identifiers", source="personhog", client_name="posthog-django"
        )
        mock_errors_counter.labels.assert_not_called()

    @patch(_ROUTING_ERRORS_PATCH)
    @patch(_ROUTING_TOTAL_PATCH)
    @patch(_CONVERTER_PATCH)
    @patch(_CLIENT_PATCH)
    def test_personhog_filters_out_groups_with_zero_id(
        self, mock_get_client, mock_convert, mock_routing_counter, mock_errors_counter
    ):
        proto_with_id = _make_proto_group(id=5, team_id=self.team_id, group_key="k1")
        proto_no_id = _make_proto_group(id=0, team_id=self.team_id, group_key="k2")

        mock_response = MagicMock()
        mock_response.groups = [proto_with_id, proto_no_id]
        mock_client = MagicMock()
        mock_client.get_groups.return_value = mock_response
        mock_get_client.return_value = mock_client

        model1 = MagicMock()
        mock_convert.return_value = model1

        result = get_groups_by_identifiers(self.team_id, self.group_type_index, ["k1", "k2"])

        assert len(result) == 1
        assert result[0] is model1
        mock_convert.assert_called_once_with(proto_with_id)

    @patch(_ROUTING_ERRORS_PATCH)
    @patch(_ROUTING_TOTAL_PATCH)
    @patch(_CLIENT_PATCH)
    def test_personhog_failure_falls_back_to_orm(self, mock_get_client, mock_routing_counter, mock_errors_counter):
        mock_client = MagicMock()
        mock_client.get_groups.side_effect = RuntimeError("grpc timeout")
        mock_get_client.return_value = mock_client

        from posthog.models.group.group import Group

        with patch.object(Group, "objects") as mock_objects:
            orm_groups = [MagicMock(spec=Group), MagicMock(spec=Group)]
            mock_qs = MagicMock()
            mock_qs.__iter__ = MagicMock(return_value=iter(orm_groups))
            mock_objects.filter.return_value = mock_qs

            result = get_groups_by_identifiers(self.team_id, self.group_type_index, ["k1", "k2"])

            assert result == orm_groups
            mock_errors_counter.labels.assert_called_once_with(
                operation="get_groups_by_identifiers",
                source="personhog",
                error_type="grpc_error",
                client_name="posthog-django",
            )
            calls = [str(c) for c in mock_routing_counter.labels.call_args_list]
            assert any("django_orm" in c for c in calls)

    @patch(_ROUTING_TOTAL_PATCH)
    @patch(_CLIENT_PATCH)
    def test_personhog_client_none_falls_back_to_orm_silently(self, mock_get_client, mock_routing_counter):
        mock_get_client.return_value = None

        from posthog.models.group.group import Group

        with patch.object(Group, "objects") as mock_objects:
            orm_groups = [MagicMock(spec=Group)]
            mock_qs = MagicMock()
            mock_qs.__iter__ = MagicMock(return_value=iter(orm_groups))
            mock_objects.filter.return_value = mock_qs

            result = get_groups_by_identifiers(self.team_id, self.group_type_index, ["k1"])

            assert result == orm_groups
            mock_routing_counter.labels.assert_called_once_with(
                operation="get_groups_by_identifiers", source="django_orm", client_name="posthog-django"
            )

    @parameterized.expand(
        [
            ("grpc_timeout", RuntimeError("grpc timeout")),
            ("connection_refused", ConnectionError("connection refused")),
            ("generic_exception", Exception("unexpected")),
        ]
    )
    @patch(_ROUTING_ERRORS_PATCH)
    @patch(_ROUTING_TOTAL_PATCH)
    @patch(_CLIENT_PATCH)
    def test_error_types_always_increment_error_metric(
        self, _name, exception, mock_get_client, mock_routing_counter, mock_errors_counter
    ):
        mock_client = MagicMock()
        mock_client.get_groups.side_effect = exception
        mock_get_client.return_value = mock_client

        from posthog.models.group.group import Group

        with patch.object(Group, "objects") as mock_objects:
            mock_qs = MagicMock()
            mock_qs.__iter__ = MagicMock(return_value=iter([]))
            mock_objects.filter.return_value = mock_qs

            get_groups_by_identifiers(self.team_id, self.group_type_index, ["k1"])

            mock_errors_counter.labels.assert_called_once()


class TestGetGroupByKeyEdgeCases(SimpleTestCase):
    @patch(_ROUTING_ERRORS_PATCH)
    @patch(_ROUTING_TOTAL_PATCH)
    @patch(_CLIENT_PATCH)
    def test_personhog_returns_none_group_returns_none(
        self, mock_get_client, mock_routing_counter, mock_errors_counter
    ):
        mock_response = MagicMock()
        mock_response.group = None
        mock_client = MagicMock()
        mock_client.get_group.return_value = mock_response
        mock_get_client.return_value = mock_client

        result = get_group_by_key(10, 0, "org:123")

        assert result is None
        mock_routing_counter.labels.assert_called_with(
            operation="get_group_by_key", source="personhog", client_name="posthog-django"
        )

    @patch(_ROUTING_ERRORS_PATCH)
    @patch(_ROUTING_TOTAL_PATCH)
    @patch(_CLIENT_PATCH)
    def test_orm_fallback_passes_correct_filter_kwargs(
        self, mock_get_client, mock_routing_counter, mock_errors_counter
    ):
        mock_client = MagicMock()
        mock_client.get_group.side_effect = RuntimeError("grpc timeout")
        mock_get_client.return_value = mock_client

        from posthog.models.group.group import Group

        with patch.object(Group, "objects") as mock_objects:
            mock_objects.get.side_effect = Group.DoesNotExist

            get_group_by_key(10, 2, "company:456")

            mock_objects.get.assert_called_once_with(team_id=10, group_type_index=2, group_key="company:456")

    @patch(_ROUTING_ERRORS_PATCH)
    @patch(_ROUTING_TOTAL_PATCH)
    @patch(_CONVERTER_PATCH)
    @patch(_CLIENT_PATCH)
    def test_converter_exception_falls_back_to_orm(
        self, mock_get_client, mock_convert, mock_routing_counter, mock_errors_counter
    ):
        proto_group = _make_proto_group(id=7, team_id=10, group_key="org:123")
        mock_response = MagicMock()
        mock_response.group = proto_group
        mock_client = MagicMock()
        mock_client.get_group.return_value = mock_response
        mock_get_client.return_value = mock_client

        mock_convert.side_effect = ValueError("malformed JSON")

        from posthog.models.group.group import Group

        with patch.object(Group, "objects") as mock_objects:
            mock_group = MagicMock(spec=Group)
            mock_objects.get.return_value = mock_group

            result = get_group_by_key(10, 0, "org:123")

            assert result is mock_group
            mock_errors_counter.labels.assert_called_once()


class TestGetGroupsByIdentifiersEdgeCases(SimpleTestCase):
    @patch(_ROUTING_ERRORS_PATCH)
    @patch(_ROUTING_TOTAL_PATCH)
    @patch(_CLIENT_PATCH)
    def test_orm_fallback_passes_correct_filter_kwargs(
        self, mock_get_client, mock_routing_counter, mock_errors_counter
    ):
        mock_client = MagicMock()
        mock_client.get_groups.side_effect = RuntimeError("grpc timeout")
        mock_get_client.return_value = mock_client

        from posthog.models.group.group import Group

        with patch.object(Group, "objects") as mock_objects:
            mock_qs = MagicMock()
            mock_qs.__iter__ = MagicMock(return_value=iter([]))
            mock_objects.filter.return_value = mock_qs

            get_groups_by_identifiers(10, 2, ["k1", "k2"])

            mock_objects.filter.assert_called_once_with(team_id=10, group_type_index=2, group_key__in=["k1", "k2"])

    @patch(_ROUTING_ERRORS_PATCH)
    @patch(_ROUTING_TOTAL_PATCH)
    @patch(_CONVERTER_PATCH)
    @patch(_CLIENT_PATCH)
    def test_all_groups_have_zero_id_returns_empty_list(
        self, mock_get_client, mock_convert, mock_routing_counter, mock_errors_counter
    ):
        proto_g1 = _make_proto_group(id=0, team_id=10, group_key="k1")
        proto_g2 = _make_proto_group(id=0, team_id=10, group_key="k2")

        mock_response = MagicMock()
        mock_response.groups = [proto_g1, proto_g2]
        mock_client = MagicMock()
        mock_client.get_groups.return_value = mock_response
        mock_get_client.return_value = mock_client

        result = get_groups_by_identifiers(10, 0, ["k1", "k2"])

        assert result == []
        mock_convert.assert_not_called()


class TestGetGroupsByTypeIndices(SimpleTestCase):
    def setUp(self):
        self.team_id = 10

    def test_empty_group_type_indices_returns_empty_list(self):
        result = get_groups_by_type_indices(self.team_id, set(), {"k1"})
        assert result == []

    def test_empty_group_keys_returns_empty_list(self):
        result = get_groups_by_type_indices(self.team_id, {0, 1}, set())
        assert result == []

    @patch(_ROUTING_ERRORS_PATCH)
    @patch(_ROUTING_TOTAL_PATCH)
    @patch(_CONVERTER_PATCH)
    @patch(_CLIENT_PATCH)
    def test_personhog_success_creates_cross_product_identifiers(
        self, mock_get_client, mock_convert, mock_routing_counter, mock_errors_counter
    ):
        proto_g1 = _make_proto_group(id=1, team_id=self.team_id, group_key="k1", group_type_index=0)
        proto_g2 = _make_proto_group(id=2, team_id=self.team_id, group_key="k2", group_type_index=1)

        mock_response = MagicMock()
        mock_response.groups = [proto_g1, proto_g2]
        mock_client = MagicMock()
        mock_client.get_groups.return_value = mock_response
        mock_get_client.return_value = mock_client

        model1, model2 = MagicMock(), MagicMock()
        mock_convert.side_effect = [model1, model2]

        result = get_groups_by_type_indices(self.team_id, {0, 1}, {"k1", "k2"})

        assert result == [model1, model2]
        mock_client.get_groups.assert_called_once()
        call_args = mock_client.get_groups.call_args[0][0]
        assert call_args.team_id == self.team_id
        assert len(call_args.group_identifiers) == 4

        mock_routing_counter.labels.assert_called_with(
            operation="get_groups_by_type_indices", source="personhog", client_name="posthog-django"
        )
        mock_errors_counter.labels.assert_not_called()

    @patch(_ROUTING_ERRORS_PATCH)
    @patch(_ROUTING_TOTAL_PATCH)
    @patch(_CONVERTER_PATCH)
    @patch(_CLIENT_PATCH)
    def test_personhog_filters_out_zero_id_groups(
        self, mock_get_client, mock_convert, mock_routing_counter, mock_errors_counter
    ):
        proto_with_id = _make_proto_group(id=5, team_id=self.team_id, group_key="k1")
        proto_no_id = _make_proto_group(id=0, team_id=self.team_id, group_key="k2")

        mock_response = MagicMock()
        mock_response.groups = [proto_with_id, proto_no_id]
        mock_client = MagicMock()
        mock_client.get_groups.return_value = mock_response
        mock_get_client.return_value = mock_client

        model1 = MagicMock()
        mock_convert.return_value = model1

        result = get_groups_by_type_indices(self.team_id, {0, 1}, {"k1", "k2"})

        assert len(result) == 1
        mock_convert.assert_called_once_with(proto_with_id)

    @patch(_ROUTING_ERRORS_PATCH)
    @patch(_ROUTING_TOTAL_PATCH)
    @patch(_CLIENT_PATCH)
    def test_personhog_failure_falls_back_to_orm_with_correct_filters(
        self, mock_get_client, mock_routing_counter, mock_errors_counter
    ):
        mock_client = MagicMock()
        mock_client.get_groups.side_effect = RuntimeError("grpc timeout")
        mock_get_client.return_value = mock_client

        from posthog.models.group.group import Group

        with patch.object(Group, "objects") as mock_objects:
            orm_groups = [MagicMock(spec=Group), MagicMock(spec=Group)]
            mock_qs = MagicMock()
            mock_qs.__iter__ = MagicMock(return_value=iter(orm_groups))
            mock_objects.filter.return_value = mock_qs

            result = get_groups_by_type_indices(self.team_id, {0, 2}, {"k1", "k2"})

            assert result == orm_groups
            mock_objects.filter.assert_called_once_with(
                team_id=self.team_id, group_type_index__in={0, 2}, group_key__in={"k1", "k2"}
            )
            mock_errors_counter.labels.assert_called_once()
            calls = [str(c) for c in mock_routing_counter.labels.call_args_list]
            assert any("django_orm" in c for c in calls)

    @patch(_ROUTING_TOTAL_PATCH)
    @patch(_CLIENT_PATCH)
    def test_personhog_client_none_falls_back_to_orm_silently(self, mock_get_client, mock_routing_counter):
        mock_get_client.return_value = None

        from posthog.models.group.group import Group

        with patch.object(Group, "objects") as mock_objects:
            orm_groups = [MagicMock(spec=Group)]
            mock_qs = MagicMock()
            mock_qs.__iter__ = MagicMock(return_value=iter(orm_groups))
            mock_objects.filter.return_value = mock_qs

            result = get_groups_by_type_indices(self.team_id, {0}, {"k1"})

            assert result == orm_groups
            mock_routing_counter.labels.assert_called_once_with(
                operation="get_groups_by_type_indices", source="django_orm", client_name="posthog-django"
            )

    @parameterized.expand(
        [
            ("grpc_timeout", RuntimeError("grpc timeout")),
            ("connection_refused", ConnectionError("connection refused")),
            ("generic_exception", Exception("unexpected")),
        ]
    )
    @patch(_ROUTING_ERRORS_PATCH)
    @patch(_ROUTING_TOTAL_PATCH)
    @patch(_CLIENT_PATCH)
    def test_error_types_always_increment_error_metric(
        self, _name, exception, mock_get_client, mock_routing_counter, mock_errors_counter
    ):
        mock_client = MagicMock()
        mock_client.get_groups.side_effect = exception
        mock_get_client.return_value = mock_client

        from posthog.models.group.group import Group

        with patch.object(Group, "objects") as mock_objects:
            mock_qs = MagicMock()
            mock_qs.__iter__ = MagicMock(return_value=iter([]))
            mock_objects.filter.return_value = mock_qs

            get_groups_by_type_indices(self.team_id, {0}, {"k1"})

            mock_errors_counter.labels.assert_called_once()


class TestOrmDatabaseErrorHandling(SimpleTestCase):
    @patch(_ROUTING_ERRORS_PATCH)
    @patch(_ROUTING_TOTAL_PATCH)
    @patch(_CLIENT_PATCH)
    def test_get_group_by_key_orm_database_error_returns_none(
        self, mock_get_client, mock_routing_counter, mock_errors_counter
    ):
        mock_client = MagicMock()
        mock_client.get_group.side_effect = RuntimeError("grpc timeout")
        mock_get_client.return_value = mock_client

        from posthog.models.group.group import Group

        with patch.object(Group, "objects") as mock_objects:
            mock_objects.get.side_effect = DatabaseError("connection lost")

            result = get_group_by_key(10, 0, "org:123")

            assert result is None

    @patch(_ROUTING_ERRORS_PATCH)
    @patch(_ROUTING_TOTAL_PATCH)
    @patch(_CLIENT_PATCH)
    def test_get_groups_by_identifiers_orm_database_error_returns_empty_list(
        self, mock_get_client, mock_routing_counter, mock_errors_counter
    ):
        mock_client = MagicMock()
        mock_client.get_groups.side_effect = RuntimeError("grpc timeout")
        mock_get_client.return_value = mock_client

        from posthog.models.group.group import Group

        with patch.object(Group, "objects") as mock_objects:
            mock_objects.filter.side_effect = DatabaseError("connection lost")

            result = get_groups_by_identifiers(10, 0, ["k1", "k2"])

            assert result == []

    @patch(_ROUTING_ERRORS_PATCH)
    @patch(_ROUTING_TOTAL_PATCH)
    @patch(_CLIENT_PATCH)
    def test_get_groups_by_type_indices_orm_database_error_returns_empty_list(
        self, mock_get_client, mock_routing_counter, mock_errors_counter
    ):
        mock_client = MagicMock()
        mock_client.get_groups.side_effect = RuntimeError("grpc timeout")
        mock_get_client.return_value = mock_client

        from posthog.models.group.group import Group

        with patch.object(Group, "objects") as mock_objects:
            mock_objects.filter.side_effect = DatabaseError("connection lost")

            result = get_groups_by_type_indices(10, {0, 1}, {"k1", "k2"})

            assert result == []


class TestCreateGroup(SimpleTestCase):
    def setUp(self):
        self.team_id = 10
        self.group_type_index: GroupTypeIndex = 0
        self.group_key = "org:123"
        self.properties = {"name": "Acme"}

    @patch("posthog.models.group.util.raw_create_group_ch")
    @patch(_ROUTING_TOTAL_PATCH)
    @patch(_CONVERTER_PATCH)
    @patch(_CLIENT_PATCH)
    def test_personhog_success_returns_converted_model(
        self, mock_get_client, mock_convert, mock_routing_counter, mock_ch
    ):
        proto_group = _make_proto_group(id=42, team_id=self.team_id, group_key=self.group_key)
        mock_response = MagicMock()
        mock_response.group = proto_group
        mock_client = MagicMock()
        mock_client.create_group.return_value = mock_response
        mock_get_client.return_value = mock_client

        fake_model = MagicMock()
        mock_convert.return_value = fake_model

        result = create_group(
            team_id=self.team_id,
            group_type_index=self.group_type_index,
            group_key=self.group_key,
            properties=self.properties,
        )

        assert result is fake_model
        mock_client.create_group.assert_called_once()
        req = mock_client.create_group.call_args[0][0]
        assert req.team_id == self.team_id
        assert req.group_type_index == self.group_type_index
        assert req.group_key == self.group_key
        assert b'"name": "Acme"' in req.group_properties
        mock_routing_counter.labels.assert_called_with(
            operation="create_group", source="personhog", client_name="posthog-django"
        )
        mock_ch.assert_called_once()

    @patch("posthog.models.group.util.raw_create_group_ch")
    @patch(_ROUTING_TOTAL_PATCH)
    @patch(_CLIENT_PATCH)
    def test_personhog_client_none_falls_back_to_orm(self, mock_get_client, mock_routing_counter, mock_ch):
        mock_get_client.return_value = None

        from posthog.models.group.group import Group

        with patch.object(Group, "objects") as mock_objects:
            mock_group = MagicMock(spec=Group)
            mock_objects.create.return_value = mock_group

            result = create_group(
                team_id=self.team_id,
                group_type_index=self.group_type_index,
                group_key=self.group_key,
                properties=self.properties,
            )

            assert result is mock_group
            mock_objects.create.assert_called_once()
            mock_routing_counter.labels.assert_called_with(
                operation="create_group", source="django_orm", client_name="posthog-django"
            )

    @parameterized.expand(
        [
            ("grpc_timeout", RuntimeError("grpc timeout")),
            ("connection_error", ConnectionError("connection refused")),
        ]
    )
    @patch("posthog.models.group.util.raw_create_group_ch")
    @patch(_ROUTING_ERRORS_PATCH)
    @patch(_ROUTING_TOTAL_PATCH)
    @patch(_CLIENT_PATCH)
    def test_personhog_exception_falls_back_to_orm(
        self, _name, exception, mock_get_client, mock_routing_counter, mock_errors_counter, mock_ch
    ):
        mock_client = MagicMock()
        mock_client.create_group.side_effect = exception
        mock_get_client.return_value = mock_client

        from posthog.models.group.group import Group

        with patch.object(Group, "objects") as mock_objects:
            mock_group = MagicMock(spec=Group)
            mock_objects.create.return_value = mock_group

            result = create_group(
                team_id=self.team_id,
                group_type_index=self.group_type_index,
                group_key=self.group_key,
                properties=self.properties,
            )

            assert result is mock_group
            mock_errors_counter.labels.assert_called_once_with(
                operation="create_group",
                source="personhog",
                error_type="grpc_error",
                client_name="posthog-django",
            )

    @patch("posthog.models.group.util.raw_create_group_ch")
    @patch(_ROUTING_TOTAL_PATCH)
    @patch(_CLIENT_PATCH)
    def test_clickhouse_write_always_happens(self, mock_get_client, mock_routing_counter, mock_ch):
        mock_get_client.return_value = None

        from posthog.models.group.group import Group

        with patch.object(Group, "objects") as mock_objects:
            mock_objects.create.return_value = MagicMock(spec=Group)
            create_group(
                team_id=self.team_id,
                group_type_index=self.group_type_index,
                group_key=self.group_key,
                properties=self.properties,
            )
            mock_ch.assert_called_once()


class TestSaveGroup(SimpleTestCase):
    def _make_group_instance(self):
        mock_group = MagicMock()
        mock_group.team_id = 10
        mock_group.group_type_index = 0
        mock_group.group_key = "org:123"
        mock_group.group_properties = {"name": "Acme"}
        return mock_group

    @patch(_ROUTING_TOTAL_PATCH)
    @patch(_CLIENT_PATCH)
    def test_personhog_success_does_not_call_orm_save(self, mock_get_client, mock_routing_counter):
        mock_client = MagicMock()
        mock_client.update_group.return_value = MagicMock()
        mock_get_client.return_value = mock_client

        group = self._make_group_instance()
        save_group(group)

        mock_client.update_group.assert_called_once()
        req = mock_client.update_group.call_args[0][0]
        assert req.team_id == 10
        assert req.group_type_index == 0
        assert req.group_key == "org:123"
        assert req.update_mask == ["group_properties"]
        assert b'"name": "Acme"' in req.group_properties
        group.save.assert_not_called()
        mock_routing_counter.labels.assert_called_with(
            operation="group_save", source="personhog", client_name="posthog-django"
        )

    @patch(_ROUTING_TOTAL_PATCH)
    @patch(_CLIENT_PATCH)
    def test_client_none_falls_back_to_orm_save(self, mock_get_client, mock_routing_counter):
        mock_get_client.return_value = None

        group = self._make_group_instance()
        save_group(group)

        group.save.assert_called_once()
        mock_routing_counter.labels.assert_called_with(
            operation="group_save", source="django_orm", client_name="posthog-django"
        )

    @parameterized.expand(
        [
            ("grpc_timeout", RuntimeError("grpc timeout")),
            ("connection_error", ConnectionError("connection refused")),
        ]
    )
    @patch(_ROUTING_ERRORS_PATCH)
    @patch(_ROUTING_TOTAL_PATCH)
    @patch(_CLIENT_PATCH)
    def test_personhog_exception_falls_back_to_orm_save(
        self, _name, exception, mock_get_client, mock_routing_counter, mock_errors_counter
    ):
        mock_client = MagicMock()
        mock_client.update_group.side_effect = exception
        mock_get_client.return_value = mock_client

        group = self._make_group_instance()
        save_group(group)

        group.save.assert_called_once()
        mock_errors_counter.labels.assert_called_once_with(
            operation="group_save",
            source="personhog",
            error_type="grpc_error",
            client_name="posthog-django",
        )
