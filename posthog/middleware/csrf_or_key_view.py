from django.middleware.csrf import CsrfViewMiddleware

from posthog.auth import PersonalAPIKeyAuthentication


class CsrfOrKeyViewMiddleware(CsrfViewMiddleware):
    """Middleware accepting requests that either contain a valid CSRF token or a personal API key."""

    def process_view(self, request, callback, callback_args, callback_kwargs):
        result = super().process_view(request, callback, callback_args, callback_kwargs)  # None if request accepted
        # if super().process_view did not find a valid CSRF token, try looking for a personal API key
        if result is not None and PersonalAPIKeyAuthentication.find_key_with_source(request) is not None:
            return self._accept(request)
        return result

    def _accept(self, request):
        request.csrf_processing_done = True
        return None
