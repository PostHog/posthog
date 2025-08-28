# posthog/person_db_router.py
from django.conf import settings


class PersonDBRouter:
    """
    A router to control all database operations on models in the persons database.
    """

    # Set of models (lowercase) that should live in the persons_db
    # Add other models from the plan here as needed.
    PERSONS_DB_MODELS = {
        "person",
        "persondistinctid",
        "personlessdistinctid",  # Assuming app_label 'posthog'
        "personoverridemapping",  # Assuming app_label 'posthog'
        "personoverride",  # Assuming app_label 'posthog'
        "pendingpersonoverride",  # Assuming app_label 'posthog'
        "flatpersonoverride",  # Assuming app_label 'posthog'
        "featureflaghashkeyoverride",  # Assuming app_label 'posthog'
        "cohortpeople",  # Assuming app_label 'posthog'
        "groups",  # Assuming app_label 'posthog'
        "grouptypemapping",  # Assuming app_label 'posthog'
    }
    PERSONS_DB_APP_LABEL = "persons_database"
    POSTHOG_APP_LABEL = "posthog"

    def db_for_read(self, model, **hints):
        """
        Attempts to read person models go to persons_db_writer.
        """
        # All models from persons_database app go to persons_db_writer
        if model._meta.app_label == self.PERSONS_DB_APP_LABEL:
            return "persons_db_writer"
        # For backward compatibility, check if it's a person model in posthog app
        """
        if model._meta.app_label == self.POSTHOG_APP_LABEL and self.is_persons_model(model._meta.model_name):
            return "persons_db_writer"
        """
        return "default"  # Allow default db selection

    def db_for_write(self, model, **hints):
        """
        Attempts to write person models go to persons_db_writer.
        """
        # All models from persons_database app go to persons_db_writer
        if model._meta.app_label == self.PERSONS_DB_APP_LABEL:
            return "persons_db_writer"
        # For backward compatibility, check if it's a person model in posthog app
        """
        if model._meta.app_label == self.POSTHOG_APP_LABEL and self.is_persons_model(model._meta.model_name):
            return "persons_db_writer"
        """
        return "default"  # Allow default db selection

    def allow_relation(self, obj1, obj2, **hints):
        """
        Allow relations if a model in PERSONS_DB_MODELS is involved.
        Relations between two models that are both in PERSONS_DB_MODELS are allowed.
        Relations between two models that are *not* in PERSONS_DB_MODELS are allowed.
        Relations between a model in PERSONS_DB_MODELS and a model not in it are DISALLOWED
        by default, as Django doesn't support cross-database relations natively.
        You might need to adjust this based on specific foreign keys (e.g., Person -> Team).
        """
        obj1_in_persons_db = obj1._meta.app_label == self.PERSONS_DB_APP_LABEL and self.is_persons_model(
            obj1._meta.model_name
        )
        obj2_in_persons_db = obj2._meta.app_label == self.PERSONS_DB_APP_LABEL and self.is_persons_model(
            obj2._meta.model_name
        )

        if obj1_in_persons_db and obj2_in_persons_db:
            # Both models are in persons_db, allow relation there
            return True
        elif not obj1_in_persons_db and not obj2_in_persons_db:
            # Neither model is in persons_db, allow relation on default db
            return None  # Allow default behavior (usually True on 'default' db)
        else:
            # One model is in persons_db, the other is not. Disallow by default.
            # You might need specific logic here for allowed cross-db FKs.
            # For example, if obj1 is Person and obj2 is Team, you might want to return True
            # if the foreign key constraint is removed or handled appropriately.
            # For now, returning False prevents potential issues.
            return False

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        """
        Make sure the person models only appear in the 'persons_db'
        database. All other models migrate normally on 'default'.
        """
        # persons_database app migrations should only migrate against persons_db_writer when enabled
        if app_label == self.PERSONS_DB_APP_LABEL:
            if settings.ENABLE_PERSONS_DB_MIGRATIONS:
                return db == "persons_db_writer"
            else:
                # When migrations are disabled, don't run them on any database
                return False

        # explicitly deny all other apps from migrating to persons_db_writer
        if db == "persons_db_writer":
            return False

        # default db will handle all other apps
        return db == "default"

    def is_persons_model(self, model_name):
        # Check if the model name belongs to the persons_db models
        return model_name in self.PERSONS_DB_MODELS
