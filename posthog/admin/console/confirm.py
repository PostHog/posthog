import secrets

from django import forms
from django.core import signing
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile, UploadedFile
from django.http import HttpRequest, QueryDict
from django.utils.datastructures import MultiValueDict

import structlog

from posthog.dataclasses import frozen

logger = structlog.get_logger(__name__)

# Long enough to read a preview, short enough that a forgotten tab cannot confirm a stale one tomorrow.
MAX_AGE_SECONDS = 15 * 60
SALT = "posthog.admin.console.confirm"
UPLOAD_CACHE_PREFIX = "admin_console_confirm_upload:"


@frozen
class ConfirmedInput:
    data: QueryDict
    files: MultiValueDict[str, UploadedFile]


class ConfirmationToken:
    """Carries what staff submitted from the preview page to the confirm button.

    The confirm submit holds only this token, and the form is bound from it, so the operation runs exactly the
    input the preview showed. The token is signed, not encrypted: a form with a preview must not hold secrets.
    It is bound to the staff member, the operation and its target, so it cannot confirm anything else. The
    handler still checks the current state, because the records may have changed since the preview.

    A browser cannot send an uploaded file again from the confirm page, so the token names a cache entry that
    holds the file until the token expires.
    """

    def __init__(self, request: HttpRequest, target: str, operation_key: str) -> None:
        self.request = request
        self.scope = {
            "actor": request.user.pk,
            "target": target,
            "operation": operation_key,
            "query": request.META.get("QUERY_STRING", ""),
            # Handlers build idempotency keys from the nonce, so the confirm must post the one the preview had.
            "form_nonce": request.POST.get("form_nonce", ""),
        }
        self.upload_keys: list[str] = []

    def sign(self, form: forms.Form) -> str:
        # Signs the form's data, not the request, so a preview can add what it showed, for example the rows it
        # selected, and the confirm step acts on exactly those.
        submitted = form.data
        assert isinstance(submitted, QueryDict)
        data = {name: submitted.getlist(name) for name in form.fields if name in submitted}
        uploads = {}
        for name in form.fields:
            upload = self.request.FILES.get(name)
            if upload is None:
                continue
            upload.seek(0)
            cache_key = UPLOAD_CACHE_PREFIX + secrets.token_urlsafe(32)
            cache.set(
                cache_key,
                {"name": upload.name, "content_type": upload.content_type, "content": upload.read()},
                MAX_AGE_SECONDS,
            )
            uploads[name] = cache_key
        return signing.dumps({**self.scope, "data": data, "uploads": uploads}, salt=SALT)

    def load(self, token: str) -> ConfirmedInput | None:
        """The submitted form input, or None when the token is forged, expired, or made for something else."""
        try:
            payload = signing.loads(token, salt=SALT, max_age=MAX_AGE_SECONDS)
        except signing.BadSignature:
            return None
        if not isinstance(payload, dict) or {key: payload.get(key) for key in self.scope} != self.scope:
            return None
        data = QueryDict(mutable=True)
        for name, values in payload.get("data", {}).items():
            data.setlist(name, values)
        files: MultiValueDict[str, UploadedFile] = MultiValueDict()
        for name, cache_key in payload.get("uploads", {}).items():
            upload = cache.get(cache_key)
            if upload is None:
                return None
            files[name] = SimpleUploadedFile(upload["name"], upload["content"], upload["content_type"])
            self.upload_keys.append(cache_key)
        return ConfirmedInput(data=data, files=files)

    def discard_uploads(self) -> None:
        """Drops the cached files once the operation ran, so a confirmed upload does not wait out its expiry."""
        # The operation already ran and the files expire anyway, so a cache failure must not fail the request.
        try:
            cache.delete_many(self.upload_keys)
        except Exception:
            logger.warning("admin_console_confirm_uploads_not_discarded", exc_info=True)
