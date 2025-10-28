from django.conf import settings

# Models that should always be routed to the local DB, even when connected to prod PG in debug
MODELS_FORCED_LOCAL_IN_PROD_DEBUG = [
    "Conversation",
    "ConversationCheckpoint",
    "ConversationCheckpointBlob",
    "ConversationCheckpointWrite",
]


class ReplicaRouter:
    def __init__(self, opt_in=None):
        self.opt_in = opt_in if opt_in else settings.READ_REPLICA_OPT_IN

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
        if settings.IS_CONNECTED_TO_PROD_PG_IN_DEBUG:
            # When connected to prod PG in debug, we want most models to go to the prod DB (`replica`),
            # and only select models use the local `default` - those where we need entities to be created locally
            return "replica" if model.__name__ not in MODELS_FORCED_LOCAL_IN_PROD_DEBUG else "default"

        if "ALL_MODELS_USE_READ_REPLICA" in self.opt_in:
            # We couldn't be more explicit with this value! This can be useful during data migrations, incidents, or testing
            return "replica"

        return "replica" if model.__name__ in self.opt_in else "default"

    def db_for_write(self, model, **hints):
        """
        Writes always go to the writer endpoint
        """
        if settings.IS_CONNECTED_TO_PROD_PG_IN_DEBUG:
            # When connected to prod PG in debug, we need writes to go to the production `replica` too,
            # _even though_ it's a read-only user
            return "replica" if model.__name__ not in MODELS_FORCED_LOCAL_IN_PROD_DEBUG else "default"
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
