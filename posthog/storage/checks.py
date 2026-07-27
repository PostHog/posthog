from django.conf import settings
from django.core.checks import Error, register

from posthog.storage.object_storage import is_usable_endpoint


@register()
def check_object_storage_public_endpoint(app_configs, **kwargs):
    """Catch a misconfigured OBJECT_STORAGE_PUBLIC_ENDPOINT at startup rather than in user traffic.

    An unsubstituted deployment template literal (e.g. `https://${POSTHOG_DOMAIN}`) makes boto3
    raise `ValueError` on client construction, which previously surfaced as 500s on every
    hypercache-backed read. Failing the system check makes the bad rollout obvious immediately.
    """
    errors: list[Error] = []

    endpoint = settings.OBJECT_STORAGE_PUBLIC_ENDPOINT
    if settings.OBJECT_STORAGE_ENABLED and endpoint and not is_usable_endpoint(endpoint):
        errors.append(
            Error(
                f"OBJECT_STORAGE_PUBLIC_ENDPOINT is not a usable URL: {endpoint!r}",
                hint="Check the deployment env — it likely contains an unsubstituted ${...} template placeholder.",
                id="posthog.E004",
            )
        )

    return errors
