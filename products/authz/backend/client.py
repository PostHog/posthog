import os

from openfga_sdk.client.configuration import ClientConfiguration
from openfga_sdk.credentials import CredentialConfiguration, Credentials
from openfga_sdk.sync import OpenFgaClient

DEFAULT_OPENFGA_STORE_NAME = "posthog-authz"


def get_openfga_client() -> OpenFgaClient:
    api_token = os.getenv("OPENFGA_API_TOKEN")
    credentials = (
        Credentials(method="api_token", configuration=CredentialConfiguration(api_token=api_token))
        if api_token
        else Credentials()
    )
    store_id = os.getenv("OPENFGA_STORE_ID")
    client = OpenFgaClient(
        ClientConfiguration(
            api_url=os.getenv("OPENFGA_API_URL", "http://127.0.0.1:8080"),
            store_id=store_id,
            authorization_model_id=os.getenv("OPENFGA_AUTHORIZATION_MODEL_ID"),
            credentials=credentials,
            timeout_millisec=5000,
        )
    )
    if store_id is None:
        try:
            store_name = os.getenv("OPENFGA_STORE_NAME") or DEFAULT_OPENFGA_STORE_NAME
            stores = client.list_stores({"name": store_name}).stores or []
            store = next((store for store in stores if store.name == store_name), None)
            if store is not None:
                client.set_store_id(store.id)
        except Exception:
            client.close()
            raise
    return client
