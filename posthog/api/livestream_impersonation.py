from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from django.conf import settings
from django.contrib.auth import SESSION_KEY
from django.core.signing import BadSignature, TimestampSigner
from django.db import router
from django.utils import timezone

from loginas import settings as loginas_settings

from posthog.dataclasses import frozen
from posthog.models.oauth import OAuthAccessToken
from posthog.scopes import scopes_not_covered
from posthog.session.activity import session_public_id
from posthog.session.models import Session
from posthog.utils import get_safe_cache, safe_cache_set


@frozen
class LivestreamImpersonation:
    impersonated_by_id: int
    source_type: Literal["session", "oauth"]
    source_id: str
    expires_at: datetime

    @property
    def cache_key(self) -> str:
        return f"{self.impersonated_by_id}:{self.source_type}:{self.source_id}"

    def claims(self) -> dict[str, str | int]:
        return {
            "impersonated_by_id": self.impersonated_by_id,
            "impersonation_source_type": self.source_type,
            "impersonation_source_id": self.source_id,
        }

    @classmethod
    def from_session(cls, session_key: str, user_id: int, impersonated_by_id: int) -> "LivestreamImpersonation | None":
        session = (
            Session.objects.using(router.db_for_write(Session))
            .filter(session_key=session_key, expire_date__gt=timezone.now())
            .first()
        )
        if session is None:
            return None
        data = session.get_decoded()
        try:
            original_user_id = TimestampSigner().unsign(
                data[loginas_settings.USER_SESSION_FLAG], max_age=settings.IMPERSONATION_TIMEOUT_SECONDS
            )
            if int(original_user_id) != impersonated_by_id or int(data[SESSION_KEY]) != user_id:
                return None
            created_at = float(data[settings.SESSION_COOKIE_CREATED_AT_KEY])
            last_activity = float(data.get(settings.IMPERSONATION_COOKIE_LAST_ACTIVITY_KEY, created_at))
            expires_at = min(
                session.expire_date,
                datetime.fromtimestamp(created_at + settings.IMPERSONATION_TIMEOUT_SECONDS, tz=UTC),
                datetime.fromtimestamp(last_activity + settings.IMPERSONATION_IDLE_TIMEOUT_SECONDS, tz=UTC),
            )
        except (BadSignature, KeyError, TypeError, ValueError, OverflowError):
            return None
        if expires_at <= timezone.now():
            return None
        return cls(
            impersonated_by_id=impersonated_by_id,
            source_type="session",
            source_id=str(session_public_id(session_key)),
            expires_at=expires_at,
        )

    @classmethod
    def from_oauth(cls, token_id: str, user_id: int, impersonated_by_id: int) -> "LivestreamImpersonation | None":
        try:
            source_id = UUID(token_id)
        except ValueError:
            return None
        token = (
            OAuthAccessToken.objects.using(router.db_for_write(OAuthAccessToken))
            .filter(id=source_id, user_id=user_id, impersonated_by_id=impersonated_by_id, expires__gt=timezone.now())
            .first()
        )
        if token is None or (
            "*" not in token.scope.split() and scopes_not_covered(token.scope.split(), ["query:read"])
        ):
            return None
        expires_at = min(
            token.expires,
            token.created
            + timedelta(
                seconds=min(settings.IMPERSONATION_IDLE_TIMEOUT_SECONDS, settings.IMPERSONATION_TIMEOUT_SECONDS)
            ),
        )
        if expires_at <= timezone.now():
            return None
        return cls(
            impersonated_by_id=impersonated_by_id,
            source_type="oauth",
            source_id=str(token.pk),
            expires_at=expires_at,
        )

    def bind_session(self, session_key: str) -> bool:
        # Keep the login credential server-side; viewer claims carry only its opaque public reference.
        cache_key = f"livestream_impersonation_session:{self.source_id}"
        safe_cache_set(cache_key, session_key, timeout=int((self.expires_at - timezone.now()).total_seconds()))
        return get_safe_cache(cache_key) == session_key

    @classmethod
    def verify(cls, claims: Mapping[str, object], user_id: int, impersonated_by_id: int) -> bool:
        source_id = claims.get("impersonation_source_id")
        if not isinstance(source_id, str) or not source_id:
            return False
        if claims.get("impersonation_source_type") == "oauth":
            return cls.from_oauth(source_id, user_id, impersonated_by_id) is not None
        if claims.get("impersonation_source_type") == "session":
            session_key = get_safe_cache(f"livestream_impersonation_session:{source_id}")
            if not isinstance(session_key, str):
                return False
            source = cls.from_session(session_key, user_id, impersonated_by_id)
            return source is not None and source.source_id == source_id
        return False
