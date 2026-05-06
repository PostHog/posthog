# Test cases for data-imports-http-transport rules.
# These fixtures are matched against the rule patterns by `pytest .semgrep/`.
# ruff: noqa: F401, F841, E501
#
# `paths.include` in the rule scopes the matchers to
# `posthog/temporal/data_imports/sources/**`, but for the test fixture the
# paths setting is ignored — semgrep applies the rule directly to this file.

import httpx
import requests
from requests import Request, Response, Session
from requests.exceptions import HTTPError, RequestException


# ============================================================
# Should flag: direct requests.<verb>
# ============================================================


def bad_requests_get():
    # ruleid: data-imports-http-transport-requests-verb
    return requests.get("https://api.example.com/")


def bad_requests_post():
    # ruleid: data-imports-http-transport-requests-verb
    return requests.post("https://api.example.com/", json={"a": 1})


def bad_requests_put():
    # ruleid: data-imports-http-transport-requests-verb
    return requests.put("https://api.example.com/", json={})


def bad_requests_patch():
    # ruleid: data-imports-http-transport-requests-verb
    return requests.patch("https://api.example.com/", json={})


def bad_requests_delete():
    # ruleid: data-imports-http-transport-requests-verb
    return requests.delete("https://api.example.com/")


def bad_requests_head():
    # ruleid: data-imports-http-transport-requests-verb
    return requests.head("https://api.example.com/")


def bad_requests_options():
    # ruleid: data-imports-http-transport-requests-verb
    return requests.options("https://api.example.com/")


def bad_requests_request():
    # ruleid: data-imports-http-transport-requests-verb
    return requests.request("GET", "https://api.example.com/")


# ============================================================
# Should flag: requests.Session()
# ============================================================


def bad_session():
    # ruleid: data-imports-http-transport-requests-session
    return requests.Session()


def bad_session_with_kwargs():
    # ruleid: data-imports-http-transport-requests-session
    sess = requests.Session()
    sess.headers.update({"X-Custom": "value"})
    return sess


# ============================================================
# Should flag: httpx.Client / httpx.<verb>
# ============================================================


def bad_httpx_client():
    # ruleid: data-imports-http-transport-httpx-client
    return httpx.Client()


def bad_httpx_async_client():
    # ruleid: data-imports-http-transport-httpx-client
    return httpx.AsyncClient()


def bad_httpx_get():
    # ruleid: data-imports-http-transport-httpx-client
    return httpx.get("https://api.example.com/")


def bad_httpx_post():
    # ruleid: data-imports-http-transport-httpx-client
    return httpx.post("https://api.example.com/", json={})


# ============================================================
# Should NOT flag: type and exception imports
# ============================================================


def ok_request_type_annotation(req: Request, resp: Response) -> None:
    pass


def ok_session_type_annotation(sess: Session) -> None:
    pass


def ok_exception_handling():
    try:
        do_something()
    except HTTPError:
        pass
    except RequestException:
        pass


def do_something() -> None:
    pass


# ============================================================
# Should NOT flag: tracked session (the supported path)
# ============================================================


def ok_tracked_session():
    from posthog.temporal.data_imports.sources.common.http import make_tracked_session

    session = make_tracked_session()
    return session.get("https://api.example.com/")
