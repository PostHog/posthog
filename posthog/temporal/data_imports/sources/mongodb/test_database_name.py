import pytest
from unittest.mock import patch

from posthog.temporal.data_imports.sources.generated_configs import MongoDBSourceConfig
from posthog.temporal.data_imports.sources.mongodb.mongo import DATABASE_NAME_REQUIRED_ERROR, _parse_connection_string
from posthog.temporal.data_imports.sources.mongodb.source import (
    _DNS_RESOLUTION_FAILURE_MARKERS,
    _MONGO_HOST_UNRESOLVED_MESSAGE,
    _MONGO_UNREACHABLE_MESSAGE,
    MongoDBSource,
)

_SRV_NO_DB = "mongodb+srv://user:pass@cluster.abc.mongodb.net/?retryWrites=true&w=majority"
_SRV_WITH_DB = "mongodb+srv://user:pass@cluster.abc.mongodb.net/realdb?retryWrites=true"


class TestParseConnectionStringDatabaseOverride:
    def test_uses_override_when_connection_string_omits_database(self):
        # Atlas SRV strings routinely have no `/<db>` path — the separate field fills it.
        params = _parse_connection_string(_SRV_NO_DB, database_override="mydb")
        assert params["database"] == "mydb"

    def test_connection_string_database_wins_over_override(self):
        params = _parse_connection_string(_SRV_WITH_DB, database_override="ignored")
        assert params["database"] == "realdb"

    @pytest.mark.parametrize("override", [None, "", "   "])
    def test_no_usable_override_leaves_database_empty(self, override):
        # The trailing `/` makes the parsed path empty, so `database` is falsy
        # (the downstream "is db missing" checks treat "" and None the same).
        params = _parse_connection_string(_SRV_NO_DB, database_override=override)
        assert not params["database"]


class TestMongoValidateCredentialsDatabaseName:
    def test_missing_database_everywhere_returns_actionable_error(self):
        config = MongoDBSourceConfig.from_dict({"connection_string": _SRV_NO_DB})

        ok, err = MongoDBSource().validate_credentials(config, team_id=1)

        assert ok is False
        assert err == DATABASE_NAME_REQUIRED_ERROR

    @patch("posthog.temporal.data_imports.sources.mongodb.source.get_collection_names")
    def test_database_name_field_satisfies_requirement(self, mock_get_collections):
        mock_get_collections.return_value = ["users"]
        config = MongoDBSourceConfig.from_dict({"connection_string": _SRV_NO_DB, "database_name": "mydb"})

        ok, err = MongoDBSource().validate_credentials(config, team_id=1)

        assert ok is True
        assert err is None


class TestMongoValidateCredentialsServerSelection:
    @pytest.mark.parametrize("marker", _DNS_RESOLUTION_FAILURE_MARKERS)
    @patch("posthog.temporal.data_imports.sources.mongodb.source.get_collection_names")
    def test_dns_resolution_failure_returns_unresolved_message(self, mock_get_collections, marker):
        from pymongo.errors import ServerSelectionTimeoutError

        # The verbose topology-description message pymongo raises when the host doesn't resolve.
        mock_get_collections.side_effect = ServerSelectionTimeoutError(
            f"cluster0.qwi73.mongodb.net:27017: [Errno -5] {marker} "
            "(configured timeouts: socketTimeoutMS: 20000.0ms), Topology Description: <TopologyDescription ...>"
        )
        config = MongoDBSourceConfig.from_dict({"connection_string": _SRV_WITH_DB})

        ok, err = MongoDBSource().validate_credentials(config, team_id=1)

        assert ok is False
        assert err == _MONGO_HOST_UNRESOLVED_MESSAGE
        assert "Topology Description" not in (err or "")

    @patch("posthog.temporal.data_imports.sources.mongodb.source.get_collection_names")
    def test_unreachable_cluster_returns_allowlist_message(self, mock_get_collections):
        from pymongo.errors import ServerSelectionTimeoutError

        mock_get_collections.side_effect = ServerSelectionTimeoutError(
            "No servers found yet, Topology Description: ..."
        )
        config = MongoDBSourceConfig.from_dict({"connection_string": _SRV_WITH_DB})

        ok, err = MongoDBSource().validate_credentials(config, team_id=1)

        assert ok is False
        assert err == _MONGO_UNREACHABLE_MESSAGE
