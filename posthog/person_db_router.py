# posthog/person_db_router.py

import threading
import contextlib

from django.conf import settings


class PersonsDBORMBlockedError(RuntimeError):
    """Raised when the Django ORM attempts to touch a persons-DB model while ORM
    access is blocked.

    personhog is the sole source of truth for person/group/cohort data. The test
    suite activates this block (via the personhog fake) so that any code path that
    still reaches for the persons DB through the ORM fails loudly instead of
    silently reading stale/empty rows. Use the personhog helpers
    (``posthog/models/person/util.py``, ``posthog/models/group_type_mapping.py``)
    for production reads and ``posthog/test/persons.py`` for test data.
    """


# Thread-local toggle. Off by default so production, migrations, management
# commands and the e2e/demo data paths route to the persons DB as before; the
# test fixture flips it on for the duration of each test.
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
    test's personhog fake is active — management commands and the demo-data
    generator, which the router is designed to let "route to the persons DB as
    before". Saves and restores the previous block state so nesting is safe.
    """
    previously_blocked = persons_orm_blocked()
    _orm_block.enabled = False
    try:
        yield
    finally:
        _orm_block.enabled = previously_blocked


# Set of models (lowercase) that should live in the persons_db
# Add other models from the plan here as needed.
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


# Database connections for persons-related operations
# In tests, use persons_db_writer for reads to ensure transaction visibility
# (both aliases point to same DB but are separate connections with separate transactions)
# In production, use persons_db_reader for read scaling
# For hobby deployments without separate persons DB, fallback to default
def _get_persons_db_for_read():
    if settings.TEST or settings.DEBUG:
        return "persons_db_writer" if "persons_db_writer" in settings.DATABASES else "default"
    return "persons_db_reader" if "persons_db_reader" in settings.DATABASES else "default"


def _get_persons_db_for_write():
    return "persons_db_writer" if "persons_db_writer" in settings.DATABASES else "default"


PERSONS_DB_FOR_READ = _get_persons_db_for_read()
PERSONS_DB_FOR_WRITE = _get_persons_db_for_write()


class PersonDBRouter:
    """
    A router to control all database operations on models in the persons database.
    """

    # Apps whose models can live in the persons DB. FeatureFlagHashKeyOverride
    # was historically in the `posthog` app; it moved to `feature_flags` when the
    # FF models were extracted, but the physical table still lives in persons_db.
    # Likewise CohortPeople moved to `cohorts`, keeping its posthog_cohortpeople table.
    PERSONS_APP_LABELS = {"posthog", "feature_flags", "cohorts"}

    def db_for_read(self, model, **hints):
        """
        Attempts to read person models go to persons_db (writer in tests, reader in production).
        """
        if self.is_persons_model(model._meta.app_label, model._meta.model_name):
            self._raise_if_blocked(model)
            return PERSONS_DB_FOR_READ
        return None  # Allow default db selection

    def db_for_write(self, model, **hints):
        """
        Attempts to write person models go to persons_db_writer.
        """
        if self.is_persons_model(model._meta.app_label, model._meta.model_name):
            # Django also calls db_for_write to compute _state.db when an FK *instance*
            # is assigned during Model.__init__ (e.g. ``GroupTypeMapping(team=team)``).
            # In that case hints["instance"] is the *related* object — a different model
            # — and nothing is being written, so it must not trip the block. Real writes
            # pass the model's own instance (save/create) or no instance (queryset writes).
            instance = hints.get("instance")
            if instance is None or isinstance(instance, model):
                self._raise_if_blocked(model)
            return PERSONS_DB_FOR_WRITE
        return None  # Allow default db selection

    @staticmethod
    def _raise_if_blocked(model) -> None:
        if persons_orm_blocked():
            raise PersonsDBORMBlockedError(
                f"Direct ORM access to persons-DB model {model._meta.label} is blocked. "
                f"personhog is the sole source of truth — read via the helpers in "
                f"posthog/models/person/util.py or posthog/models/group_type_mapping.py, "
                f"and create test data via posthog/test/persons.py."
            )

    def allow_relation(self, obj1, obj2, **hints):
        """
        Allow relations if a model in PERSONS_DB_MODELS is involved.
        Relations between two models that are both in PERSONS_DB_MODELS are allowed.
        Relations between two models that are *not* in PERSONS_DB_MODELS are allowed.
        Relations between a model in PERSONS_DB_MODELS and a model not in it are DISALLOWED
        by default, as Django doesn't support cross-database relations natively.
        You might need to adjust this based on specific foreign keys (e.g., Person -> Team).
        """
        obj1_in_persons_db = obj1._meta.app_label in self.PERSONS_APP_LABELS and self.is_persons_model(
            obj1._meta.app_label, obj1._meta.model_name
        )
        obj2_in_persons_db = obj2._meta.app_label in self.PERSONS_APP_LABELS and self.is_persons_model(
            obj2._meta.app_label, obj2._meta.model_name
        )

        if obj1_in_persons_db and obj2_in_persons_db:
            # Both models are in persons_db, allow relation there
            return True
        elif not obj1_in_persons_db and not obj2_in_persons_db:
            # Neither model is in persons_db, allow relation on default db
            return None  # Allow default behavior (usually True on 'default' db)
        else:
            # One model is in persons_db, the other is not.
            # Allow specific cross-database relationships where the FK constraint is removed (db_constraint=False)
            # Person -> Team: Person.team has db_constraint=False
            # GroupTypeMapping -> Team: GroupTypeMapping.team has db_constraint=False
            # GroupTypeMapping -> Project: GroupTypeMapping.project has db_constraint=False
            # GroupTypeMapping -> Dashboard: GroupTypeMapping.detail_dashboard has db_constraint=False
            from posthog.models import Person, Project, Team
            from posthog.models.group_type_mapping import GroupTypeMapping

            from products.cohorts.backend.models.cohort import Cohort, CohortPeople
            from products.dashboards.backend.models.dashboard import Dashboard

            # Allow any persons_db model -> Team relation
            # (Person, PersonDistinctId, Group, CohortPeople, etc. all have team FK)
            if isinstance(obj2, Team) and obj1_in_persons_db:
                return True
            if isinstance(obj1, Team) and obj2_in_persons_db:
                return True

            # Allow GroupTypeMapping -> Project relation
            if isinstance(obj1, GroupTypeMapping) and isinstance(obj2, Project):
                return True
            if isinstance(obj1, Project) and isinstance(obj2, GroupTypeMapping):
                return True

            # Allow GroupTypeMapping -> Dashboard relation
            if isinstance(obj1, GroupTypeMapping) and isinstance(obj2, Dashboard):
                return True
            if isinstance(obj1, Dashboard) and isinstance(obj2, GroupTypeMapping):
                return True

            # Allow Cohort -> CohortPeople relation (for cohort.people.add())
            if isinstance(obj1, Cohort) and isinstance(obj2, Person | CohortPeople):
                return True
            if isinstance(obj1, Person | CohortPeople) and isinstance(obj2, Cohort):
                return True

            # Disallow all other cross-database relations
            return False

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        """
        don't run any migrations against the persons db, only against the default
        run all migrations against the default
        """
        return db != "persons_db_writer"

    def is_persons_model(self, app_label, model_name):
        # only route posthog app models, not auth.Group (there is a name clash between posthog_group
        # and Django's auth_group. featureflaghashkeyoverride moved to the feature_flags app but the
        # physical table still lives in persons_db.
        return app_label in self.PERSONS_APP_LABELS and model_name in PERSONS_DB_MODELS
