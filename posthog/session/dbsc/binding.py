import time
import secrets
from datetime import datetime
from typing import Any, Literal, cast

from django.contrib.sessions.backends.base import SessionBase
from django.http import HttpRequest
from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.session.backend import DBSC_CARRY_SESSION_KEY
from posthog.session.models import Session

Algorithm = Literal["ES256", "RS256"]

OFFER_SESSION_KEY = "_dbsc_offer"
# Long enough to register. A session that never registers must not stay claimable by whoever holds its cookie.
OFFER_TTL_SECONDS = 10 * 60
_LOGIN_OFFER_ATTR = "_dbsc_login_offer"


@frozen
class Binding:
    # Random, so it stays the same when the session key rotates.
    id: str
    alg: Algorithm
    jwk: dict[str, Any]
    bound_at: datetime

    def to_json(self) -> dict[str, Any]:
        return {"id": self.id, "alg": self.alg, "jwk": self.jwk, "bound_at": self.bound_at.isoformat()}

    @classmethod
    def from_json(cls, raw: object) -> "Binding | None":
        if not isinstance(raw, dict):
            return None
        try:
            alg = raw["alg"]
            if alg not in ("ES256", "RS256") or not isinstance(raw["jwk"], dict) or not isinstance(raw["id"], str):
                return None
            return cls(
                id=raw["id"],
                alg=cast(Algorithm, alg),
                jwk=raw["jwk"],
                bound_at=datetime.fromisoformat(raw["bound_at"]),
            )
        except (KeyError, TypeError, ValueError):
            return None


def new_binding(*, alg: Algorithm, jwk: dict[str, Any]) -> Binding:
    return Binding(id=secrets.token_urlsafe(16), alg=alg, jwk=jwk, bound_at=timezone.now())


def current_binding(session: SessionBase) -> Binding | None:
    """Reuses the row the session store already loaded, because this runs on every request."""
    session_key = session.session_key
    if not session_key:
        return None
    loaded = cast("Session | None", getattr(session, "loaded_row", None))
    if loaded is not None and loaded.session_key == session_key:
        return Binding.from_json(loaded.dbsc_binding)
    raw = Session.objects.filter(session_key=session_key).values_list("dbsc_binding", flat=True).first()
    return Binding.from_json(raw)


def save_binding(session_key: str, binding: Binding) -> bool:
    """Only an unbound row takes a key, so a stolen session cookie cannot move the binding to another device."""
    updated = Session.objects.filter(session_key=session_key, dbsc_binding__isnull=True).update(
        dbsc_binding=binding.to_json()
    )
    return updated == 1


def carry_binding(session: SessionBase, binding: Binding) -> None:
    """A login on the same browser replaces the session row, and the device key stays in that browser."""
    session[DBSC_CARRY_SESSION_KEY] = binding.to_json()
    session.pop(OFFER_SESSION_KEY, None)


def carry_into_impersonation(session: SessionBase, staff_binding: Binding | None) -> None:
    """An impersonation stays bound to the staff member's device, and is never offered a binding of its own."""
    if staff_binding is not None:
        carry_binding(session, staff_binding)
    else:
        session.pop(OFFER_SESSION_KEY, None)


def is_bound_or_carried(session: SessionBase) -> bool:
    return DBSC_CARRY_SESSION_KEY in session or current_binding(session) is not None


def new_offer(request: HttpRequest) -> None:
    request.session[OFFER_SESSION_KEY] = {
        "id": secrets.token_urlsafe(16),
        "expires_at": time.time() + OFFER_TTL_SECONDS,
    }
    setattr(request, _LOGIN_OFFER_ATTR, True)


def offer_id(session: SessionBase) -> str | None:
    offer = session.get(OFFER_SESSION_KEY)
    if not isinstance(offer, dict) or not isinstance(offer.get("id"), str):
        return None
    expires_at = offer.get("expires_at")
    if not isinstance(expires_at, int | float) or expires_at <= time.time():
        return None
    return offer["id"]


def is_login_response(request: HttpRequest) -> bool:
    return bool(getattr(request, _LOGIN_OFFER_ATTR, False))
