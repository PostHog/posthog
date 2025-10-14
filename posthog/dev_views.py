"""
Development-only views. Only available when DEBUG=1.
"""

import requests
from django.conf import settings
from django.http import HttpRequest, HttpResponse


def vite_worker_proxy(request: HttpRequest, path: str) -> HttpResponse:
    """
    Proxy worker requests to the Vite dev server.
    This avoids cross-origin issues with module workers in development.
    """
    # Include query string if present
    query_string = request.META.get('QUERY_STRING', '')
    vite_url = f"http://localhost:8234/{path}"
    if query_string:
        vite_url += f"?{query_string}"

    print(f"[VITE PROXY] Proxying request to: {vite_url}")

    try:
        response = requests.get(vite_url, timeout=5)
        print(f"[VITE PROXY] Response status: {response.status_code}, content-type: {response.headers.get('content-type')}")

        # Check if this is a binary file (wasm) that shouldn't be rewritten
        content_type = response.headers.get('content-type', '')
        is_binary = content_type.startswith('application/wasm')

        if is_binary:
            # For binary files, return as-is without any rewriting
            django_response = HttpResponse(
                response.content,  # Use .content for binary data
                status=response.status_code,
                content_type=content_type
            )
            # Copy relevant headers
            for header in ['etag', 'cache-control']:
                if header in response.headers:
                    django_response[header] = response.headers[header]
            return django_response

        # Get content and rewrite URLs to point back to our proxy
        content = response.text

        # Rewrite various forms of localhost:8234 URLs to use our proxy
        content = content.replace('http://localhost:8234/', 'http://localhost:8010/_vite/')
        content = content.replace('"http://localhost:8234', '"http://localhost:8010/_vite')
        content = content.replace("'http://localhost:8234", "'http://localhost:8010/_vite")

        # Special case: Fix snappy_bg.wasm path (Vite generates wrong path for wasm in workers)
        # The bundle references node_modules/.vite/deps/snappy_bg.wasm but it doesn't exist there
        # The actual file is in the source package, accessible via @fs path
        content = content.replace(
            'http://localhost:8010/_vite/node_modules/.vite/deps/snappy_bg.wasm',
            'http://localhost:8010/_vite/@fs/Users/pauldambra/github/posthog/node_modules/.pnpm/snappy-wasm@0.3.0/node_modules/snappy-wasm/es/snappy_bg.wasm'
        )

        # Rewrite absolute paths to proxy them through Django
        # This handles imports like: from "/node_modules/.vite/deps/..."
        import re
        # Match import statements with absolute paths
        content = re.sub(
            r'(import\s+[^"\']*\s+from\s+["\'])(/[^"\']+)(["\'])',
            r'\1http://localhost:8010/_vite\2\3',
            content
        )
        # Also match standalone import statements: import "/path/to/file"
        content = re.sub(
            r'(import\s+)(["\'])(/[^"\']+)(["\'])',
            r'\1\2http://localhost:8010/_vite\3\4',
            content
        )

        print(f"[VITE PROXY] Response length: {len(content)} chars")
        if 'import' in content[:200]:
            print(f"[VITE PROXY] Response starts with: {content[:200]}")

        # Create Django response with rewritten content
        django_response = HttpResponse(
            content,
            status=response.status_code,
            content_type=response.headers.get('content-type', 'application/javascript')
        )

        # Copy relevant headers
        for header in ['etag', 'cache-control']:
            if header in response.headers:
                django_response[header] = response.headers[header]

        return django_response

    except requests.RequestException as e:
        print(f"[VITE PROXY] Error: {e}")
        return HttpResponse(f"Failed to proxy to Vite dev server: {e}", status=502)
