from types import SimpleNamespace

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

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

    @patch(_CLIENT_PATCH)
    def test_client_none_raises(self, mock_get_client):
        mock_get_client.return_value = None

        with self.assertRaises(RuntimeError):
            get_group_by_key(self.team_id, self.group_type_index, self.group_key)

    @patch(_ROUTING_TOTAL_PATCH)
    @patch(_CONVERTER_PATCH)
    @patch(_CLIENT_PATCH)
    def test_personhog_returns_group_converts_and_returns_model(
        self, mock_get_client, mock_convert, mock_routing_counter
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

    @patch(_ROUTING_TOTAL_PATCH)
    @patch(_CLIENT_PATCH)
    def test_personhog_returns_group_with_zero_id_returns_none(self, mock_get_client, mock_routing_counter):
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

    @patch(_ROUTING_TOTAL_PATCH)
    @patch(_CLIENT_PATCH)
    def test_personhog_exception_propagates(self, mock_get_client, mock_routing_counter):
        mock_client = MagicMock()
        mock_client.get_group.side_effect = RuntimeError("grpc timeout")
        mock_get_client.return_value = mock_client

        with self.assertRaises(RuntimeError):
            get_group_by_key(self.team_id, self.group_type_index, self.group_key)


class TestGetGroupsByIdentifiers(SimpleTestCase):
    def setUp(self):
        self.team_id = 10
        self.group_type_index = 0

    @override_settings(PERSONHOG_BATCH_SIZE=2)
    @patch(_ROUTING_TOTAL_PATCH)
    @patch(_CONVERTER_PATCH)
    @patch(_CLIENT_PATCH)
    def test_personhog_chunks_requests(self, mock_get_client, mock_convert, mock_routing_counter):
        # 5 keys with batch size 2 → 3 chunks (2 + 2 + 1)
        protos = [_make_proto_group(id=i + 1, team_id=self.team_id, group_key=f"k{i}") for i in range(5)]
        mock_client = MagicMock()
        mock_client.get_groups.side_effect = [
            MagicMock(groups=protos[0:2]),
            MagicMock(groups=protos[2:4]),
            MagicMock(groups=protos[4:5]),
        ]
        mock_get_client.return_value = mock_client
        models = [MagicMock() for _ in range(5)]
        mock_convert.side_effect = models

        result = get_groups_by_identifiers(self.team_id, self.group_type_index, [f"k{i}" for i in range(5)])

        assert result == models
        assert mock_client.get_groups.call_count == 3
        for call in mock_client.get_groups.call_args_list:
            assert len(call[0][0].group_identifiers) <= 2

    def test_empty_group_keys_returns_empty_list_without_personhog(self):
        with patch(_CLIENT_PATCH) as mock_get_client:
            result = get_groups_by_identifiers(self.team_id, self.group_type_index, [])

            assert result == []
            mock_get_client.assert_not_called()

    @patch(_ROUTING_TOTAL_PATCH)
    @patch(_CONVERTER_PATCH)
    @patch(_CLIENT_PATCH)
    def test_personhog_success_returns_converted_models(self, mock_get_client, mock_convert, mock_routing_counter):
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

    @patch(_ROUTING_TOTAL_PATCH)
    @patch(_CONVERTER_PATCH)
    @patch(_CLIENT_PATCH)
    def test_personhog_filters_out_groups_with_zero_id(self, mock_get_client, mock_convert, mock_routing_counter):
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

    @patch(_CLIENT_PATCH)
    def test_client_none_raises(self, mock_get_client):
        mock_get_client.return_value = None

        with self.assertRaises(RuntimeError):
            get_groups_by_identifiers(self.team_id, self.group_type_index, ["k1"])

    @patch(_ROUTING_TOTAL_PATCH)
    @patch(_CLIENT_PATCH)
    def test_personhog_exception_propagates(self, mock_get_client, mock_routing_counter):
        mock_client = MagicMock()
        mock_client.get_groups.side_effect = RuntimeError("grpc timeout")
        mock_get_client.return_value = mock_client

        with self.assertRaises(RuntimeError):
            get_groups_by_identifiers(self.team_id, self.group_type_index, ["k1", "k2"])


class TestGetGroupsByIdentifiersEdgeCases(SimpleTestCase):
    @patch(_ROUTING_TOTAL_PATCH)
    @patch(_CONVERTER_PATCH)
    @patch(_CLIENT_PATCH)
    def test_all_groups_have_zero_id_returns_empty_list(self, mock_get_client, mock_convert, mock_routing_counter):
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

    @override_settings(PERSONHOG_BATCH_SIZE=2)
    @patch(_ROUTING_TOTAL_PATCH)
    @patch(_CONVERTER_PATCH)
    @patch(_CLIENT_PATCH)
    def test_personhog_chunks_cross_product(self, mock_get_client, mock_convert, mock_routing_counter):
        # {0, 1} x {k1, k2, k3} = 6 identifiers; batch size 2 → 3 chunks
        mock_client = MagicMock()
        mock_client.get_groups.side_effect = [MagicMock(groups=[]) for _ in range(3)]
        mock_get_client.return_value = mock_client

        get_groups_by_type_indices(self.team_id, {0, 1}, {"k1", "k2", "k3"})

        assert mock_client.get_groups.call_count == 3
        total = sum(len(c[0][0].group_identifiers) for c in mock_client.get_groups.call_args_list)
        assert total == 6
        for c in mock_client.get_groups.call_args_list:
            assert len(c[0][0].group_identifiers) <= 2

    def test_empty_group_type_indices_returns_empty_list(self):
        result = get_groups_by_type_indices(self.team_id, set(), {"k1"})
        assert result == []

    def test_empty_group_keys_returns_empty_list(self):
        result = get_groups_by_type_indices(self.team_id, {0, 1}, set())
        assert result == []

    @patch(_ROUTING_TOTAL_PATCH)
    @patch(_CONVERTER_PATCH)
    @patch(_CLIENT_PATCH)
    def test_personhog_success_creates_cross_product_identifiers(
        self, mock_get_client, mock_convert, mock_routing_counter
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

    @patch(_ROUTING_TOTAL_PATCH)
    @patch(_CONVERTER_PATCH)
    @patch(_CLIENT_PATCH)
    def test_personhog_filters_out_zero_id_groups(self, mock_get_client, mock_convert, mock_routing_counter):
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

    @patch(_CLIENT_PATCH)
    def test_client_none_raises(self, mock_get_client):
        mock_get_client.return_value = None

        with self.assertRaises(RuntimeError):
            get_groups_by_type_indices(self.team_id, {0}, {"k1"})

    @patch(_ROUTING_TOTAL_PATCH)
    @patch(_CLIENT_PATCH)
    def test_personhog_exception_propagates(self, mock_get_client, mock_routing_counter):
        mock_client = MagicMock()
        mock_client.get_groups.side_effect = RuntimeError("grpc timeout")
        mock_get_client.return_value = mock_client

        with self.assertRaises(RuntimeError):
            get_groups_by_type_indices(self.team_id, {0, 2}, {"k1", "k2"})


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
    @patch(_CLIENT_PATCH)
    def test_client_none_raises_after_clickhouse_write(self, mock_get_client, mock_ch):
        mock_get_client.return_value = None

        with self.assertRaises(RuntimeError):
            create_group(
                team_id=self.team_id,
                group_type_index=self.group_type_index,
                group_key=self.group_key,
                properties=self.properties,
            )

        # ClickHouse write happens before the personhog call, so it runs even when the client is missing.
        mock_ch.assert_called_once()

    @patch("posthog.models.group.util.raw_create_group_ch")
    @patch(_ROUTING_TOTAL_PATCH)
    @patch(_CLIENT_PATCH)
    def test_personhog_exception_propagates(self, mock_get_client, mock_routing_counter, mock_ch):
        mock_client = MagicMock()
        mock_client.create_group.side_effect = RuntimeError("grpc timeout")
        mock_get_client.return_value = mock_client

        with self.assertRaises(RuntimeError):
            create_group(
                team_id=self.team_id,
                group_type_index=self.group_type_index,
                group_key=self.group_key,
                properties=self.properties,
            )


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

    @patch(_CLIENT_PATCH)
    def test_client_none_raises(self, mock_get_client):
        mock_get_client.return_value = None

        group = self._make_group_instance()
        with self.assertRaises(RuntimeError):
            save_group(group)

    @patch(_ROUTING_TOTAL_PATCH)
    @patch(_CLIENT_PATCH)
    def test_personhog_exception_propagates(self, mock_get_client, mock_routing_counter):
        mock_client = MagicMock()
        mock_client.update_group.side_effect = RuntimeError("grpc timeout")
        mock_get_client.return_value = mock_client

        group = self._make_group_instance()
        with self.assertRaises(RuntimeError):
            save_group(group)
