import os
import json
from pathlib import Path

from openfga_sdk import CreateStoreRequest, WriteAuthorizationModelRequest

from products.authz.backend.client import DEFAULT_OPENFGA_STORE_NAME, get_openfga_client

MODEL_PATH = Path(__file__).resolve().parents[1] / "openfga_model.json"


def bootstrap_openfga() -> str:
    store_name = os.getenv("OPENFGA_STORE_NAME") or DEFAULT_OPENFGA_STORE_NAME
    model = json.loads(MODEL_PATH.read_text())
    client = get_openfga_client()
    try:
        if client.get_store_id() is None:
            store = client.create_store(CreateStoreRequest(name=store_name))
            client.set_store_id(store.id)

        result = client.write_authorization_model(
            WriteAuthorizationModelRequest(
                schema_version=model["schema_version"],
                type_definitions=model["type_definitions"],
                conditions=model.get("conditions"),
            )
        )
        if result.authorization_model_id is None:
            raise RuntimeError("OpenFGA did not return an authorization model ID")
        return result.authorization_model_id
    finally:
        client.close()
