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

# Patched at source because util.py uses lazy `from X import Y` inside each function body.
# `require_personhog_client` resolves the client via `get_personhog_client`, so patching that
# controls whether a client is available; `personhog_call` runs for real (its metrics and
# error wrapping are exercised by its own tests, not duplicated here).
_CLIENT_PATCH = "posthog.personhog_client.client.get_personhog_client"
_CONVERTER_PATCH = "posthog.personhog_client.converters.proto_group_to_model"


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

    @patch(_CONVERTER_PATCH)
    @patch(_CLIENT_PATCH)
    def test_returns_converted_model(self, mock_get_client, mock_convert):
        proto_group = _make_proto_group(id=7, team_id=self.team_id, group_key=self.group_key)
        mock_client = MagicMock()
        mock_client.get_group.return_value = MagicMock(group=proto_group)
        mock_get_client.return_value = mock_client

        fake_model = MagicMock()
        mock_convert.return_value = fake_model

        result = get_group_by_key(self.team_id, self.group_type_index, self.group_key)

        assert result is fake_model
        mock_convert.assert_called_once_with(proto_group)
        req = mock_client.get_group.call_args[0][0]
        assert req.team_id == self.team_id
        assert req.group_type_index == self.group_type_index
        assert req.group_key == self.group_key

    @patch(_CLIENT_PATCH)
    def test_zero_id_returns_none(self, mock_get_client):
        proto_group = _make_proto_group(id=0, team_id=self.team_id, group_key=self.group_key)
        mock_client = MagicMock()
        mock_client.get_group.return_value = MagicMock(group=proto_group)
        mock_get_client.return_value = mock_client

        assert get_group_by_key(self.team_id, self.group_type_index, self.group_key) is None

    @patch(_CLIENT_PATCH)
    def test_falsy_group_returns_none(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.get_group.return_value = MagicMock(group=None)
        mock_get_client.return_value = mock_client

        assert get_group_by_key(self.team_id, self.group_type_index, self.group_key) is None

    @patch(_CLIENT_PATCH)
    def test_missing_client_raises(self, mock_get_client):
        mock_get_client.return_value = None

        with self.assertRaises(RuntimeError):
            get_group_by_key(self.team_id, self.group_type_index, self.group_key)


class TestGetGroupsByIdentifiers(SimpleTestCase):
    def setUp(self):
        self.team_id = 10
        self.group_type_index = 0

    @override_settings(PERSONHOG_BATCH_SIZE=2)
    @patch(_CONVERTER_PATCH)
    @patch(_CLIENT_PATCH)
    def test_chunks_requests_and_returns_all_models(self, mock_get_client, mock_convert):
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

    @patch(_CONVERTER_PATCH)
    @patch(_CLIENT_PATCH)
    def test_filters_out_zero_id_groups(self, mock_get_client, mock_convert):
        proto_with_id = _make_proto_group(id=5, team_id=self.team_id, group_key="k1")
        proto_no_id = _make_proto_group(id=0, team_id=self.team_id, group_key="k2")
        mock_client = MagicMock()
        mock_client.get_groups.return_value = MagicMock(groups=[proto_with_id, proto_no_id])
        mock_get_client.return_value = mock_client
        mock_convert.return_value = MagicMock()

        result = get_groups_by_identifiers(self.team_id, self.group_type_index, ["k1", "k2"])

        assert len(result) == 1
        mock_convert.assert_called_once_with(proto_with_id)

    def test_empty_group_keys_short_circuits_without_client(self):
        with patch(_CLIENT_PATCH) as mock_get_client:
            assert get_groups_by_identifiers(self.team_id, self.group_type_index, []) == []
            mock_get_client.assert_not_called()


class TestGetGroupsByTypeIndices(SimpleTestCase):
    def setUp(self):
        self.team_id = 10

    @override_settings(PERSONHOG_BATCH_SIZE=2)
    @patch(_CONVERTER_PATCH)
    @patch(_CLIENT_PATCH)
    def test_builds_cross_product_identifiers_and_chunks(self, mock_get_client, mock_convert):
        # {0, 1} x {k1, k2} = 4 identifiers; batch size 2 → 2 chunks
        mock_client = MagicMock()
        mock_client.get_groups.side_effect = [MagicMock(groups=[]), MagicMock(groups=[])]
        mock_get_client.return_value = mock_client

        get_groups_by_type_indices(self.team_id, {0, 1}, {"k1", "k2"})

        assert mock_client.get_groups.call_count == 2
        total = sum(len(c[0][0].group_identifiers) for c in mock_client.get_groups.call_args_list)
        assert total == 4
        for c in mock_client.get_groups.call_args_list:
            assert len(c[0][0].group_identifiers) <= 2

    def test_empty_group_type_indices_returns_empty_list(self):
        assert get_groups_by_type_indices(self.team_id, set(), {"k1"}) == []

    def test_empty_group_keys_returns_empty_list(self):
        assert get_groups_by_type_indices(self.team_id, {0, 1}, set()) == []


class TestCreateGroup(SimpleTestCase):
    def setUp(self):
        self.team_id = 10
        self.group_type_index: GroupTypeIndex = 0
        self.group_key = "org:123"
        self.properties = {"name": "Acme"}

    @patch("posthog.models.group.util.raw_create_group_ch")
    @patch(_CONVERTER_PATCH)
    @patch(_CLIENT_PATCH)
    def test_builds_request_converts_response_and_writes_clickhouse(self, mock_get_client, mock_convert, mock_ch):
        proto_group = _make_proto_group(id=42, team_id=self.team_id, group_key=self.group_key)
        mock_client = MagicMock()
        mock_client.create_group.return_value = MagicMock(group=proto_group)
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
        req = mock_client.create_group.call_args[0][0]
        assert req.team_id == self.team_id
        assert req.group_type_index == self.group_type_index
        assert req.group_key == self.group_key
        assert b'"name": "Acme"' in req.group_properties
        mock_ch.assert_called_once()

    @patch("posthog.models.group.util.raw_create_group_ch")
    @patch(_CLIENT_PATCH)
    def test_clickhouse_write_happens_even_when_personhog_fails(self, mock_get_client, mock_ch):
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

        mock_ch.assert_called_once()


class TestSaveGroup(SimpleTestCase):
    def _make_group_instance(self):
        group = MagicMock()
        group.team_id = 10
        group.group_type_index = 0
        group.group_key = "org:123"
        group.group_properties = {"name": "Acme"}
        return group

    @patch(_CLIENT_PATCH)
    def test_builds_update_request_with_group_properties_mask(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        save_group(self._make_group_instance())

        req = mock_client.update_group.call_args[0][0]
        assert req.team_id == 10
        assert req.group_type_index == 0
        assert req.group_key == "org:123"
        assert req.update_mask == ["group_properties"]
        assert b'"name": "Acme"' in req.group_properties
