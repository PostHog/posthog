import hashlib
from rest_framework.throttling import SimpleRateThrottle


class UserOrEmailRateThrottle(SimpleRateThrottle):
    """
    Typically throttling is on the user or the IP address.
    For unauthenticated signup/login requests we want to throttle on the email address.
    """

    scope = "user"

    def get_cache_key(self, request, view):
        if request.user and request.user.is_authenticated:
            ident = request.user.pk
        else:
            # For unauthenticated requests, we want to throttle on something unique to the user they are trying to work with
            # This could be email for example when logging in or uuid when verifying email
            ident = request.data.get("email") or request.data.get("uuid") or self.get_ident(request)
            ident = hashlib.sha256(ident.encode()).hexdigest()

        return self.cache_format % {"scope": self.scope, "ident": ident}
