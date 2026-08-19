from django.conf import settings
from django.core.checks import Error, register

from posthog.storage.object_storage import is_usable_bucket, is_usable_endpoint


@register()
def check_object_storage_config(app_configs, **kwargs):
    """Catch misconfigured object storage at startup rather than in user traffic.

    An unsubstituted deployment template literal (e.g. `https://${POSTHOG_DOMAIN}` or
    `@@RECORDINGS_BUCKET@@`), or a hostname botocore refuses (e.g. one with an underscore), makes
    the S3 client raise on every read. That previously surfaced as repeated 500s and duplicate
    error-tracking reports. Failing the system check makes the bad rollout obvious at once.
    """
    errors: list[Error] = []

    if not settings.OBJECT_STORAGE_ENABLED:
        return errors

    endpoint = settings.OBJECT_STORAGE_ENDPOINT
    if endpoint and not is_usable_endpoint(endpoint):
        errors.append(
            Error(
                f"OBJECT_STORAGE_ENDPOINT is not a usable URL: {endpoint!r}",
                hint="Check the deployment env — it likely contains an unsubstituted placeholder or an invalid hostname.",
                id="posthog.E005",
            )
        )

    public_endpoint = settings.OBJECT_STORAGE_PUBLIC_ENDPOINT
    if public_endpoint and not is_usable_endpoint(public_endpoint):
        errors.append(
            Error(
                f"OBJECT_STORAGE_PUBLIC_ENDPOINT is not a usable URL: {public_endpoint!r}",
                hint="Check the deployment env — it likely contains an unsubstituted ${...} template placeholder.",
                id="posthog.E004",
            )
        )

    bucket = settings.OBJECT_STORAGE_BUCKET
    if bucket and not is_usable_bucket(bucket):
        errors.append(
            Error(
                f"OBJECT_STORAGE_BUCKET is not a usable bucket name: {bucket!r}",
                hint="Check the deployment env — it likely contains an unsubstituted placeholder.",
                id="posthog.E006",
            )
        )

    return errors
