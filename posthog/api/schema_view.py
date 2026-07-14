import re

from drf_spectacular.views import SpectacularAPIView

# A schema version is only ever a short identifier (e.g. "1.0", "v2"). Anything else — and in
# particular CRLF or other control characters — is rejected so it can't reach the
# Content-Disposition header, where Django would raise BadHeaderError and return a 500.
_SAFE_SCHEMA_VERSION = re.compile(r"^[\w.\-]{1,64}$")


class PostHogSpectacularAPIView(SpectacularAPIView):
    """SpectacularAPIView that ignores an unsafe ``?version=`` query param.

    drf-spectacular interpolates the raw ``version`` param into the response's
    Content-Disposition filename. Since we set no ``ALLOWED_VERSIONS``, an arbitrary value
    (e.g. one containing ``\r\n``) would otherwise flow straight into the header and trip
    Django's BadHeaderError, surfacing as a spurious 500. Drop anything that isn't a plain
    version identifier and fall back to the unversioned schema.
    """

    def _get_version_parameter(self, request):
        version = super()._get_version_parameter(request)
        if version is not None and not _SAFE_SCHEMA_VERSION.match(version):
            return None
        return version
