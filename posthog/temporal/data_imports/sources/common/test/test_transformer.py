from posthog.temporal.data_imports.sources.common.transformer import transform_payload
from posthog.warehouse.api.available_sources import AVAILABLE_SOURCES
from posthog.warehouse.models import ExternalDataSource


def test_transform_payload():
    inputs = {
        "source_type": "Postgres",
        "connection_string": "",
        "host": "127.0.0.1",
        "port": 5432,
        "database": "sdf",
        "user": "hjk",
        "password": "hjkl",
        "schema": "nklm",
        "ssh-tunnel": {
            "enabled": True,
            "host": "dgfdfg",
            "port": 17,
            "auth_type": {
                "selection": "password",
                "username": "dfg",
                "password": "dfg",
                "private_key": "",
                "passphrase": "",
            },
        },
    }
    converted_payload = transform_payload(
        payload=inputs, source_config=AVAILABLE_SOURCES[ExternalDataSource.Type.POSTGRES]
    )

    assert converted_payload == {
        "source_type": "Postgres",
        "connection_string": "",
        "host": "127.0.0.1",
        "port": 5432,
        "database": "sdf",
        "user": "hjk",
        "password": "hjkl",
        "schema": "nklm",
        "ssh-tunnel": {
            "enabled": True,
            "host": "dgfdfg",
            "port": 17,
            "auth": {  # modified field name
                "type": "password",  # modified field name
                "username": "dfg",
                "password": "dfg",
                "private_key": "",
                "passphrase": "",
            },
        },
    }
