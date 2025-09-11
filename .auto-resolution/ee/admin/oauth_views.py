from django.http import HttpRequest, HttpResponse, JsonResponse


def admin_auth_check(request: HttpRequest) -> JsonResponse:
    """
    Returns 200 if verified, otherwise the middleware will redirect to OAuth2.
    """
    return JsonResponse({"authenticated": True})


def admin_oauth_success(request: HttpRequest) -> HttpResponse:
    nonce = getattr(request, "admin_csp_nonce", "")
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>Authentication Complete</title>
    </head>
    <body>
        <h1>Authentication Successful</h1>
        <p>This window will close automatically.</p>
        <script nonce="{nonce}">
            // Notify the parent window that authentication is complete
            if (window.opener && !window.opener.closed) {{
                window.opener.postMessage({{ type: 'oauth2_complete' }}, '*');
            }}

            window.close();
        </script>
    </body>
    </html>
    """
    return HttpResponse(html)
