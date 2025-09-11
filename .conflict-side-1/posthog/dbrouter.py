from posthog.settings.data_stores import READ_REPLICA_OPT_IN


class ReplicaRouter:
    def __init__(self, opt_in=None):
        self.opt_in = opt_in if opt_in else READ_REPLICA_OPT_IN

    """
    A database router to route reads to a separate Aurora endpoint

    This adds opt-in routing for models, pointing them to the read replica.

    Many examples show several configured replicas. We use Aurora,
    so already have a load-balanced reader endpoint that handles this for us.
    Hence our database config has a single write endpoint, and single read endpoint.

    Please be aware that there is a small amount of lag (<100ms, usually significantly less)
    from the writer to reader instance. This means that you will face consistency issues if you
    immediately try and read a model you have just written.
    """

    def db_for_read(self, model, **hints):
        """
        Reads go to the replica endpoint, but only if opted in
        """
        # I don't think we could be more explicit!
        # This could be useful during data migrations, incidents, or testing
        if "ALL_MODELS_USE_READ_REPLICA" in self.opt_in:
            return "replica"

        return "replica" if model.__name__ in self.opt_in else "default"

    def db_for_write(self, model, **hints):
        """
        Writes always go to the writer endpoint
        """
        return "default"

    def allow_relation(self, obj1, obj2, **hints):
        """
        Relations are always allowed. We are not sharding (yet), so there will be no issues
        """
        return True

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        """
        Allow migrations always
        """
        return True
