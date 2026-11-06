from django import forms
from django.core import signing
from django.http import HttpRequest, QueryDict

# Long enough to read a preview, short enough that a forgotten tab cannot confirm a stale one tomorrow.
MAX_AGE_SECONDS = 15 * 60
SALT = "posthog.admin.console.confirm"


class ConfirmationToken:
    """Carries what staff submitted from the preview page to the confirm button.

    The confirm submit holds only this token, and the form is bound from it, so the operation runs exactly the
    input the preview showed. The token is signed, not encrypted: a form with a preview must not hold secrets.
    It is bound to the staff member, the operation and its target, so it cannot confirm anything else. The
    handler still checks the current state, because the records may have changed since the preview.
    """

    def __init__(self, request: HttpRequest, target: str, operation_key: str) -> None:
        self.request = request
        self.scope = {
            "actor": request.user.pk,
            "target": target,
            "operation": operation_key,
            "query": request.META.get("QUERY_STRING", ""),
        }

    def sign(self, form: forms.Form) -> str:
        data = {name: self.request.POST.getlist(name) for name in form.fields if name in self.request.POST}
        return signing.dumps({**self.scope, "data": data}, salt=SALT)

    def load(self, token: str) -> QueryDict | None:
        """The submitted form data, or None when the token is forged, expired, or made for something else."""
        try:
            payload = signing.loads(token, salt=SALT, max_age=MAX_AGE_SECONDS)
        except signing.BadSignature:
            return None
        if not isinstance(payload, dict) or {key: payload.get(key) for key in self.scope} != self.scope:
            return None
        data = QueryDict(mutable=True)
        for name, values in payload.get("data", {}).items():
            data.setlist(name, values)
        return data
