"""
Cache-aware QR code view for django-two-factor-auth to handle session race conditions.
"""

from two_factor.views import QRGeneratorView

from posthog.helpers.session_cache import SessionCache


class CacheAwareQRGeneratorView(QRGeneratorView):
    """
    QR view that retrieves secrets from cache to avoid session race conditions.

    The parent QRGeneratorView expects 'django_two_factor-qr_secret_key' in the session.
    However, concurrent requests can overwrite session data. This view retrieves from
    cache (where data is stored atomically) and injects into session for the parent view.
    """

    def get(self, request, *args, **kwargs):
        session_cache = SessionCache(request.session)
        qr_secret = session_cache.get(self.session_key_name)

        if qr_secret:
            # Inject cached value into session for parent view
            request.session[self.session_key_name] = qr_secret

        return super().get(request, *args, **kwargs)
