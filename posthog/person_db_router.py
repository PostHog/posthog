# posthog/person_db_router.py
class PersonDBRouter:
    """
    A router to control all database operations on models in the persons database.
    """

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
    PERSONS_APP_LABEL = "posthog"  # Assuming all models are in the 'posthog' app

    def db_for_read(self, model, **hints):
        """
        Attempts to read person models go to persons_db_writer.
        """
        if self.is_persons_model(model._meta.model_name):
            return "persons_db_writer"
        return None  # Allow default db selection

    def db_for_write(self, model, **hints):
        """
        Attempts to write person models go to persons_db_writer.
        """
        if self.is_persons_model(model._meta.model_name):
            return "persons_db_writer"
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
            obj1._meta.model_name
        )
        obj2_in_persons_db = obj2._meta.app_label == self.PERSONS_APP_LABEL and self.is_persons_model(
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
        if model_name is None:
            # App-level migrations should only run on the default database
            return db != "persons_db_writer"

        is_person_model = self.is_persons_model(model_name)

        if db == "persons_db_writer":
            # If the target db is persons_db_writer, only allow migration if it's a person model
            return is_person_model
        else:
            # Otherwise (e.g., target db is 'default'), only allow migration
            # if it's *not* a person model.
            return not is_person_model

    def is_persons_model(self, model_name):
        # Check if the model name belongs to the persons_db models
        return model_name in self.PERSONS_DB_MODELS
