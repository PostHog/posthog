"""
Development-only views. Only available when DEBUG=1.
"""

import re

from django.conf import settings
from django.http import HttpRequest, HttpResponse

import requests

VITE_DEV_SERVER = "http://localhost:8234"
PROXY_BASE_URL = "http://localhost:8010/_vite"


def _build_vite_url(path: str, query_string: str) -> str:
    url = f"{VITE_DEV_SERVER}/{path}"
    if query_string:
        url += f"?{query_string}"
    return url


def _copy_headers(source_response: requests.Response, target_response: HttpResponse) -> None:
    for header in ["etag", "cache-control"]:
        if header in source_response.headers:
            target_response[header] = source_response.headers[header]


def _rewrite_urls(content: str) -> str:
    content = content.replace(f"{VITE_DEV_SERVER}/", f"{PROXY_BASE_URL}/")
    content = content.replace(f'"{VITE_DEV_SERVER}', f'"{PROXY_BASE_URL}')
    content = content.replace(f"'{VITE_DEV_SERVER}", f"'{PROXY_BASE_URL}")
    return content


def _rewrite_snappy_wasm_path(content: str) -> str:
    return content.replace(
        f"{PROXY_BASE_URL}/node_modules/.vite/deps/snappy_bg.wasm",
        f"{PROXY_BASE_URL}/@fs/Users/pauldambra/github/posthog/node_modules/.pnpm/snappy-wasm@0.3.0/node_modules/snappy-wasm/es/snappy_bg.wasm",
    )


def _rewrite_import_paths(content: str) -> str:
    content = re.sub(
        r'(import\s+[^"\']*\s+from\s+["\'])(/[^"\']+)(["\'])',
        rf"\1{PROXY_BASE_URL}\2\3",
        content,
    )
    content = re.sub(
        r'(import\s+)(["\'])(/[^"\']+)(["\'])',
        rf"\1\2{PROXY_BASE_URL}\3\4",
        content,
    )
    return content


def _create_binary_response(response: requests.Response) -> HttpResponse:
    content_type = response.headers.get("content-type", "")
    django_response = HttpResponse(response.content, status=response.status_code, content_type=content_type)
    _copy_headers(response, django_response)
    return django_response


def _create_text_response(response: requests.Response) -> HttpResponse:
    content = response.text
    content = _rewrite_urls(content)
    content = _rewrite_snappy_wasm_path(content)
    content = _rewrite_import_paths(content)

    django_response = HttpResponse(
        content,
        status=response.status_code,
        content_type=response.headers.get("content-type", "application/javascript"),
    )
    _copy_headers(response, django_response)
    return django_response


def vite_worker_proxy(request: HttpRequest, path: str) -> HttpResponse:
    """
    Proxy worker requests to the Vite dev server.
    This avoids cross-origin issues with module workers in development.
    """
    if not settings.DEBUG:
        raise ValueError("This view should only be used in development (DEBUG=1)")

    vite_url = _build_vite_url(path, request.META.get("QUERY_STRING", ""))

    try:
        response = requests.get(vite_url, timeout=5)

        content_type = response.headers.get("content-type", "")
        is_binary = content_type.startswith("application/wasm")

        if is_binary:
            return _create_binary_response(response)
        else:
            return _create_text_response(response)

    except requests.RequestException as e:
        return HttpResponse(f"Failed to proxy to Vite dev server: {e}", status=502)
