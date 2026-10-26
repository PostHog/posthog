"""Recorded transport for PyPI's public JSON and Integrity APIs.

PyPI publishes no request limit for these APIs, so the calls are recorded but not gated. Requests are
anonymous: no credential is sent, so there is no account identity to budget.
"""

from typing import Any
from urllib.parse import quote

import requests

from posthog.egress.pypi.observability import pypi_egress
from posthog.egress.transport.transport import RecordedEgressClient

PYPI_URL = "https://pypi.org"


class PyPIClient(RecordedEgressClient):
    observability = pypi_egress
    egress_domain = "pypi"

    def _standard_headers(self) -> dict[str, str]:
        return {"Accept": "application/json"}


_pypi_client = PyPIClient()


def pypi_release_url(project: str, version: str) -> str:
    return f"{PYPI_URL}/pypi/{quote(project, safe='')}/{quote(version, safe='')}/json"


def pypi_provenance_url(project: str, version: str, filename: str) -> str:
    return f"{PYPI_URL}/integrity/{quote(project, safe='')}/{quote(version, safe='')}/{quote(filename, safe='')}/provenance"


def pypi_request(
    method: str,
    url: str,
    *,
    source: str,
    endpoint: str,
    timeout: float | tuple[float, float] | None = None,
    session: requests.Session | None = None,
    **kwargs: Any,
) -> requests.Response:
    return _pypi_client.request(
        method,
        url,
        source=source,
        scope="public",
        endpoint=endpoint,
        timeout=timeout,
        session=session,
        **kwargs,
    )
