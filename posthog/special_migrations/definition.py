ONE_HOUR = 60 * 60


class SpecialMigrationOperation:
    def __init__(self, sql="", database="postgres", mode="sync", timeout_seconds=60, rollback=None, resumable=False):
        self.sql = sql
        self.database = database
        self.mode = mode
        self.timeout_seconds = timeout_seconds
        self.rollback = rollback
        self.resumable = resumable


class SpecialMigrationDefinition:
    posthog_min_version = "0.0.0"
    posthog_max_version = "10000.0.0"

    service_version_requirements = []
    operations = []

    def progress():
        return 0

    def precheck():
        return (True, None)

    def cancel():
        return False

    def rollback(migration_instance):
        return False
