"""Lemlist API auth as a Dagster resource.

Lemlist uses HTTP Basic auth where the password is the API key; the username
is ignored by the server but must be present in the header. We expose the key
as a ``dagster.ConfigurableResource`` so the dag's definitions can bind it to
``dagster.EnvVar("LEMLIST_API_KEY")`` in one place — that keeps the secret
scoped to the billing dag rather than leaking into global Django settings,
and keeps it out of the Dagster UI (``EnvVar`` values are resolved lazily at
resource init time).
"""

from typing import ClassVar

import dagster
import requests
from requests.adapters import HTTPAdapter
from requests.auth import HTTPBasicAuth
from urllib3.util.retry import Retry


class LemlistNotConfiguredError(RuntimeError):
    """Raised when the Lemlist API key is empty at resource-build time."""


class LemlistAuthResource(dagster.ConfigurableResource):
    """Builds authenticated, retry-aware ``requests.Session`` instances.

    The session is created per-call rather than cached: resources inside the
    dlt source open and close their own session (``with ... as session:``), so
    a shared instance would be closed after the first resource finished.
    """

    api_key: str

    # Retry policy constants — surfaced as ClassVars so they don't leak into
    # the Pydantic-managed config surface shown in the Dagster UI.
    _RETRY_TOTAL: ClassVar[int] = 5
    _RETRY_BACKOFF_FACTOR: ClassVar[float] = 2.0
    _RETRY_STATUS_FORCELIST: ClassVar[tuple[int, ...]] = (429, 500, 502, 503, 504)

    def build_session(self) -> requests.Session:
        if not self.api_key:
            raise LemlistNotConfiguredError("Lemlist API key is empty")
        retry = Retry(
            total=self._RETRY_TOTAL,
            backoff_factor=self._RETRY_BACKOFF_FACTOR,
            status_forcelist=list(self._RETRY_STATUS_FORCELIST),
            allowed_methods=["GET", "POST"],
            respect_retry_after_header=True,
        )
        session = requests.Session()
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        session.auth = HTTPBasicAuth(username="", password=self.api_key)
        return session
