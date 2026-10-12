import os
from urllib.parse import urlsplit, urlunsplit

import structlog

from ..client import get_openfga_client
from ..facade.contracts import OpenFgaStatus

logger = structlog.get_logger(__name__)

# Same default as get_openfga_client(), which reads the same variable. Keep the two in sync.
DEFAULT_OPENFGA_API_URL = "http://127.0.0.1:8080"


def _without_userinfo(url: str) -> str:
    """Return the URL without the user name and password that a URL can carry."""
    parts = urlsplit(url)
    return urlunsplit(parts._replace(netloc=parts.netloc.rpartition("@")[2]))


def _unreachable(api_url: str, exc: Exception) -> OpenFgaStatus:
    logger.warning("openfga_status_check_failed", exc_info=exc)
    # Return only the exception class, because an SDK error message can include the response body and headers.
    return OpenFgaStatus(
        reachable=False,
        api_url=api_url,
        store_name=None,
        store_id=None,
        authorization_model_id=None,
        error=type(exc).__name__,
    )


def get_openfga_status() -> OpenFgaStatus:
    api_url = _without_userinfo(os.getenv("OPENFGA_API_URL", DEFAULT_OPENFGA_API_URL))
    try:
        client = get_openfga_client()
    except Exception as exc:
        return _unreachable(api_url, exc)
    try:
        if client.get_store_id() is None:
            # Without a configured store id, get_openfga_client() lists the stores by name. A missing id after
            # that call means the server answered and has no store with that name.
            return OpenFgaStatus(
                reachable=True,
                api_url=api_url,
                store_name=None,
                store_id=None,
                authorization_model_id=None,
                error=None,
            )
        store = client.get_store()
        model = (
            client.read_authorization_model()
            if os.getenv("OPENFGA_AUTHORIZATION_MODEL_ID")
            else client.read_latest_authorization_model()
        ).authorization_model
    except Exception as exc:
        return _unreachable(api_url, exc)
    finally:
        client.close()
    return OpenFgaStatus(
        reachable=True,
        api_url=api_url,
        store_name=store.name,
        store_id=store.id,
        authorization_model_id=model.id if model is not None else None,
        error=None,
    )
