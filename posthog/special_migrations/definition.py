class SpecialMigrationOperation:
    def __init__(self, sql="", database="clickhouse", timeout_seconds=60, rollback=None, resumable=False):
        self.sql = sql
        self.database = database
        self.timeout_seconds = timeout_seconds
        self.resumable = resumable


class SpecialMigrationDefinition:
    posthog_min_version = "0.0.0"
    posthog_max_version = "10000.0.0"

    service_version_requirements = []
    operations = []

    def is_required(self):
        return True

    def healthcheck(self):
        return (True, None)

    def progress(self, migration_instance):
        return int(100 * migration_instance.current_operation_index / len(self.operations))

    def rollback(self, _):
        return (False, None)
