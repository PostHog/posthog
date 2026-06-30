# posthog/person_db_router.py

import threading
import contextlib

from prometheus_client import Counter

# A persons-DB model resolved through the Django ORM. personhog serves person/group/cohort data,
# so this should stay at zero in production — a nonzero value means a code path still reaches a
# persons model via the ORM, which now routes to the main database instead of the persons DB.
# Alert on any increase; the model/operation labels point at the offending callsite.
PERSONS_ORM_ACCESS_COUNTER = Counter(
    "posthog_persons_orm_access_total",
    "Persons-DB model resolved through the Django ORM (expected zero in production).",
    labelnames=["model", "operation"],
)


class PersonsDBORMBlockedError(RuntimeError):
    """Raised when the Django ORM attempts to touch a persons-DB model while ORM
    access is blocked.

    personhog is the sole source of truth for person/group/cohort data. The test
    suite activates this block (via the personhog fake) so that any code path that
    still reaches for the persons DB through the ORM fails loudly instead of
    silently reading the main database. Use the personhog helpers
    (``posthog/models/person/util.py``, ``posthog/models/group_type_mapping.py``)
    for production reads and ``posthog/test/persons.py`` for test data.
    """


# Thread-local toggle. Off by default; the test fixture flips it on for the
# duration of each test so a stray persons-DB ORM call surfaces immediately.
_orm_block = threading.local()


def block_persons_orm() -> None:
    _orm_block.enabled = True


def unblock_persons_orm() -> None:
    _orm_block.enabled = False


def persons_orm_blocked() -> bool:
    return getattr(_orm_block, "enabled", False)


@contextlib.contextmanager
def allow_persons_orm():
    """Temporarily allow direct persons-DB ORM access while the block is active.

    For maintenance paths that legitimately read/write the persons DB even when a
    test's personhog fake is active. Saves and restores the previous block state so
    nesting is safe.
    """
    previously_blocked = persons_orm_blocked()
    _orm_block.enabled = False
    try:
        yield
    finally:
        _orm_block.enabled = previously_blocked


# Models (lowercase model_name) whose tables are owned by the persons database.
# personhog is the source of truth for these; the ORM must not query them.
PERSONS_DB_MODELS = {
    "person",
    "persondistinctid",
    "personlessdistinctid",
    "personoverridemapping",
    "personoverride",
    "pendingpersonoverride",
    "flatpersonoverride",
    "featureflaghashkeyoverride",
    "cohortpeople",
    "group",
    "grouptypemapping",
}


class PersonDBRouter:
    """Guards the Django ORM against touching persons-DB models.

    The persons data lives behind the personhog service, not the Django ORM, so
    this router never routes to a separate database — it returns ``None`` and lets
    the default selection stand. It raises when a persons-DB model is queried through
    the ORM while the block is active (the test fixture enables it), turning an
    otherwise-silent read of the main database into a loud failure, and increments
    ``PERSONS_ORM_ACCESS_COUNTER`` on every persons-model ORM resolution so the same
    access is observable in production, where the block is off.
    """

    # Apps whose models can live in the persons DB. FeatureFlagHashKeyOverride was
    # historically in the `posthog` app; it moved to `feature_flags` when the FF
    # models were extracted, and CohortPeople moved to `cohorts`, but both keep
    # their persons-DB tables.
    PERSONS_APP_LABELS = {"posthog", "feature_flags", "cohorts"}

    def db_for_read(self, model, **hints):
        if self.is_persons_model(model._meta.app_label, model._meta.model_name):
            self._record_orm_access(model, "read")
            self._raise_if_blocked(model)
        return None  # Allow default db selection

    def db_for_write(self, model, **hints):
        if self.is_persons_model(model._meta.app_label, model._meta.model_name):
            # Django also calls db_for_write to compute _state.db when an FK *instance*
            # is assigned during Model.__init__ (e.g. ``GroupTypeMapping(team=team)``).
            # In that case hints["instance"] is the *related* object — a different model
            # — and nothing is being written, so it must not trip the block. Real writes
            # pass the model's own instance (save/create) or no instance (queryset writes).
            instance = hints.get("instance")
            if instance is None or isinstance(instance, model):
                self._record_orm_access(model, "write")
                self._raise_if_blocked(model)
        return None  # Allow default db selection

    @staticmethod
    def _record_orm_access(model, operation: str) -> None:
        # Emit on every persons-model ORM resolution so production stray access is observable
        # even though the block is off there (see PERSONS_ORM_ACCESS_COUNTER).
        PERSONS_ORM_ACCESS_COUNTER.labels(model=model._meta.model_name, operation=operation).inc()

    @staticmethod
    def _raise_if_blocked(model) -> None:
        if persons_orm_blocked():
            raise PersonsDBORMBlockedError(
                f"Direct ORM access to persons-DB model {model._meta.label} is blocked. "
                f"personhog is the sole source of truth — read via the helpers in "
                f"posthog/models/person/util.py or posthog/models/group_type_mapping.py, "
                f"and create test data via posthog/test/persons.py."
            )

    def is_persons_model(self, app_label, model_name):
        return app_label in self.PERSONS_APP_LABELS and model_name in PERSONS_DB_MODELS
