# posthog/person_db_router.py

from django.conf import settings

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
PERSONS_DB_FOR_READ = "persons_db_writer" if settings.TEST or settings.DEBUG else "persons_db_reader"
PERSONS_DB_FOR_WRITE = "persons_db_writer"


class PersonDBRouter:
    """
    A router to control all database operations on models in the persons database.
    """

    PERSONS_APP_LABEL = "posthog"  # Assuming all models are in the 'posthog' app

    def db_for_read(self, model, **hints):
        """
        Attempts to read person models go to persons_db (writer in tests, reader in production).
        """
        if self.is_persons_model(model._meta.app_label, model._meta.model_name):
            return PERSONS_DB_FOR_READ
        return None  # Allow default db selection

    def db_for_write(self, model, **hints):
        """
        Attempts to write person models go to persons_db_writer.
        """
        if self.is_persons_model(model._meta.app_label, model._meta.model_name):
            return PERSONS_DB_FOR_WRITE
        return None  # Allow default db selection

    def allow_relation(self, obj1, obj2, **hints):
        """
        Allow relations if a model in PERSONS_DB_MODELS is involved.
        Relations between two models that are both in PERSONS_DB_MODELS are allowed.
        Relations between two models that are *not* in PERSONS_DB_MODELS are allowed.
        Relations between a model in PERSONS_DB_MODELS and a model not in it are DISALLOWED
        by default, as Django doesn't support cross-database relations natively.
        You might need to adjust this based on specific foreign keys (e.g., Person -> Team).
        """
        obj1_in_persons_db = obj1._meta.app_label == self.PERSONS_APP_LABEL and self.is_persons_model(
            obj1._meta.app_label, obj1._meta.model_name
        )
        obj2_in_persons_db = obj2._meta.app_label == self.PERSONS_APP_LABEL and self.is_persons_model(
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
            # All persons_db models -> Team: all have team FK with db_constraint=False
            # GroupTypeMapping -> Project: has db_constraint=False
            # GroupTypeMapping -> Dashboard: has db_constraint=False
            from posthog.models import Dashboard, Project, Team
            from posthog.models.group_type_mapping import GroupTypeMapping

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
        # and Django's auth_group
        return app_label == "posthog" and model_name in PERSONS_DB_MODELS
