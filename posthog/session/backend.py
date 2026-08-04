import logging
from typing import TYPE_CHECKING, Any, cast

from django.contrib.auth import SESSION_KEY
from django.contrib.sessions.backends.base import CreateError, UpdateError
from django.contrib.sessions.backends.db import SessionStore as DBStore
from django.core.exceptions import SuspiciousOperation
from django.db import DatabaseError, IntegrityError, router, transaction
from django.utils import timezone

from asgiref.sync import sync_to_async
from loginas.settings import USER_SESSION_FLAG

if TYPE_CHECKING:
    from posthog.session.models import Session

# Columns the session machinery owns and may write on save. The remaining columns (ip,
# short_user_agent, location, last_activity beyond creation) are written by the activity middleware
# and must not be reset to NULL by a routine session save.
_SESSION_OWNED_FIELDS = ["session_data", "expire_date", "user_id"]

# Columns the row load below fetches. Kept to exactly what auth needs to decode a session and know
# its user, so this every-request query can't fail on a column a later migration (display metadata,
# risk baseline, ...) hasn't landed yet — those columns are read separately by the code that wants
# them (see risk.py's own query).
_SESSION_LOAD_FIELDS = ["session_key", "session_data", "expire_date", "user_id"]


def _auth_user_id(data: dict[str, Any]) -> int | None:
    if USER_SESSION_FLAG in data:
        # Impersonation (loginas): never attribute the session to the impersonated user.
        return None
    try:
        return int(data[SESSION_KEY])
    except (KeyError, TypeError, ValueError):
        return None


class SessionStore(DBStore):
    """Database session store that keeps `user_id` on the session row in sync with `_auth_user_id`.

    The only behavioural change from Django's `db` store is that `user_id` is stamped on every save
    and that updates touch only the session-owned columns, leaving middleware-written display
    metadata intact.
    """

    @classmethod
    def get_model_class(cls):
        from posthog.session.models import Session

        return Session

    def create_model_instance(self, data: dict[str, Any]) -> "Session":
        obj = cast("Session", super().create_model_instance(data))
        obj.user_id = _auth_user_id(data)
        # Only persisted on INSERT (see `save`); for existing rows the middleware owns last_activity.
        obj.last_activity = timezone.now()
        return obj

    def _get_session_from_db(self) -> "Session | None":
        # Reimplements DBStore._get_session_from_db with a narrowed `.only()` instead of calling
        # super() — the base implementation runs an all-fields SELECT, so it would still fail on a
        # column `_SESSION_LOAD_FIELDS` deliberately excludes.
        try:
            return cast(
                "Session",
                self.model.objects.only(*_SESSION_LOAD_FIELDS).get(
                    session_key=self.session_key, expire_date__gt=timezone.now()
                ),
            )
        except (self.model.DoesNotExist, SuspiciousOperation) as e:
            if isinstance(e, SuspiciousOperation):
                logger = logging.getLogger(f"django.security.{e.__class__.__name__}")
                logger.warning(str(e))
            self._session_key = None
            return None

    async def _aget_session_from_db(self) -> "Session | None":
        try:
            return cast(
                "Session",
                await self.model.objects.only(*_SESSION_LOAD_FIELDS).aget(
                    session_key=self.session_key, expire_date__gt=timezone.now()
                ),
            )
        except (self.model.DoesNotExist, SuspiciousOperation) as e:
            if isinstance(e, SuspiciousOperation):
                logger = logging.getLogger(f"django.security.{e.__class__.__name__}")
                logger.warning(str(e))
            self._session_key = None
            return None

    def save(self, must_create: bool = False) -> None:
        if self.session_key is None:
            return self.create()
        data = self._get_session(no_load=must_create)  # type: ignore[attr-defined]  # private SessionBase method, not in django-stubs
        obj = self.create_model_instance(data)
        using = router.db_for_write(self.model, instance=obj)
        try:
            with transaction.atomic(using=using):
                self._persist(obj, must_create, using)
        except IntegrityError:
            if must_create:
                raise CreateError
            raise
        except DatabaseError:
            if not must_create:
                raise UpdateError
            raise

    async def acreate_model_instance(self, data: dict[str, Any]) -> "Session":
        obj = cast("Session", await super().acreate_model_instance(data))
        obj.user_id = _auth_user_id(data)
        obj.last_activity = timezone.now()
        return obj

    async def asave(self, must_create: bool = False) -> None:
        if self.session_key is None:
            return await self.acreate()
        data = await self._aget_session(no_load=must_create)  # type: ignore[attr-defined]  # private SessionBase method, not in django-stubs
        obj = await self.acreate_model_instance(data)
        using = router.db_for_write(self.model, instance=obj)

        @sync_to_async
        def run() -> None:
            with transaction.atomic(using=using):
                self._persist(obj, must_create, using)

        try:
            await run()
        except IntegrityError:
            if must_create:
                raise CreateError
            raise
        except DatabaseError:
            if not must_create:
                raise UpdateError
            raise

    def _persist(self, obj: "Session", must_create: bool, using: str) -> None:
        # On UPDATE, touch only the session-owned columns so middleware-written metadata survives.
        if must_create:
            obj.save(force_insert=True, using=using)
        else:
            obj.save(force_update=True, using=using, update_fields=_SESSION_OWNED_FIELDS)
