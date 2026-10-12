import os

from openfga_sdk.client.configuration import ClientConfiguration
from openfga_sdk.credentials import CredentialConfiguration, Credentials
from openfga_sdk.sync import OpenFgaClient


def get_openfga_client() -> OpenFgaClient:
    api_token = os.getenv("OPENFGA_API_TOKEN")
    credentials = (
        Credentials(method="api_token", configuration=CredentialConfiguration(api_token=api_token))
        if api_token
        else Credentials()
    )
    return OpenFgaClient(
        ClientConfiguration(
            api_url=os.getenv("OPENFGA_API_URL", "http://127.0.0.1:8080"),
            store_id=os.getenv("OPENFGA_STORE_ID"),
            credentials=credentials,
            timeout_millisec=5000,
        )
    )
